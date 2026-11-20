"""Backend-owned periodic and requested asset discovery; independent of scan scheduling."""
import asyncio
import logging
import socket
import uuid

from dsx_connect_v2.control_plane.coverage_inventory import _refresh_one
from dsx_connect_v2.control_plane.discovery_settings import DiscoverySettings, DiscoverySettingsStore
from dsx_connect_v2.control_plane.discovery_transport import _connector_asset_endpoint, _effective_asset_type, _fetch_connector_assets

log = logging.getLogger(__name__)
POLL_SECONDS = 5


async def serve(control_plane, store, *, stop=None):
    worker_id = f'{socket.gethostname()}:{uuid.uuid4().hex[:12]}'
    active = {}
    def discover(integration, cursor, config):
        asset_type = _effective_asset_type('auto', integration)
        base, name = _connector_asset_endpoint(integration, control_plane.list_connector_instances(integration_id=integration.integration_id))
        return _fetch_connector_assets(base, name, asset_type=asset_type, source='all', limit=1000,
                                       cursor=cursor, timeout_seconds=config.request_timeout_seconds), asset_type
    try:
        while stop is None or not stop.is_set():
            for key, task in list(active.items()):
                if task.done():
                    try:
                        task.result()
                    except Exception:
                        log.exception('Discovery task failed for %s; it remains eligible for retry.', key)
                    del active[key]
            try:
                await asyncio.to_thread(store.heartbeat, worker_id, len(active))
                policy = await asyncio.to_thread(store.settings)
                config = DiscoverySettings.model_validate(policy['settings'])
                integrations = await asyncio.to_thread(control_plane.list_integrations)
                due = await asyncio.to_thread(store.due_integrations, integrations, config)
                for integration in due:
                    if len(active) >= config.concurrency:
                        break
                    if integration.integration_id in active:
                        continue
                    callback = lambda row, cursor, cfg=config: discover(row, cursor, cfg)
                    active[integration.integration_id] = asyncio.create_task(asyncio.to_thread(
                        _refresh_one, store, integration, callback, config, stop.is_set if stop else None))
            except Exception:
                log.exception('Discovery coordinator failed; retrying without discarding inventory.')
            if stop:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(POLL_SECONDS)
    finally:
        # Bounded HTTP requests finish before process shutdown; locks are then released.
        if active:
            await asyncio.gather(*active.values(), return_exceptions=True)


def run():
    """Compatibility entrypoint: discovery now runs inside the Management Worker."""
    from dsx_connect_v2.workers.management_worker import run as management_run
    management_run()


if __name__ == '__main__':
    run()
