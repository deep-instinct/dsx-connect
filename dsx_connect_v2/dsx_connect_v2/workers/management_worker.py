"""One maintenance process with independent discovery and daily-aggregation tasks."""
import asyncio
import logging
import signal
import socket
import uuid

from dsx_connect_v2.control_plane.bootstrap import bootstrap_control_plane
from dsx_connect_v2.control_plane.discovery_settings import DiscoverySettingsStore
from dsx_connect_v2.jobs.daily_aggregates import DailyAggregateStore, ManagementSettings
from dsx_connect_v2.workers import discovery_worker

log = logging.getLogger(__name__)
POLL_SECONDS = 5


async def aggregate_loop(store, stop):
    while not stop.is_set():
        try:
            config = ManagementSettings(**(await asyncio.to_thread(store.settings))['settings'])
            if config.aggregates_enabled:
                await asyncio.to_thread(store.backfill_page)
                for _ in range(config.aggregate_days_per_pass if await asyncio.to_thread(store.backfill_complete) else 0):
                    if stop.is_set() or not await asyncio.to_thread(store.process_one):
                        break
        except Exception:
            log.exception('Daily aggregation failed; discovery continues and queued work is retained.')
            try:
                await asyncio.to_thread(store.record_error)
            except Exception:
                log.exception('Could not record daily aggregation status.')
        try:
            await asyncio.wait_for(stop.wait(),timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def heartbeat_loop(store, stop):
    worker_id = f'{socket.gethostname()}:{uuid.uuid4().hex[:12]}'
    while not stop.is_set():
        try:
            await asyncio.to_thread(store.heartbeat,worker_id)
        except Exception:
            log.exception('Management heartbeat failed; retrying.')
        try:
            await asyncio.wait_for(stop.wait(),timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def serve(control, discovery_store, aggregate_store, stop):
    # Separate loops and thread work prevent aggregation from occupying discovery slots.
    tasks = [asyncio.create_task(discovery_worker.serve(control,discovery_store,stop=stop)),
             asyncio.create_task(aggregate_loop(aggregate_store,stop)),
             asyncio.create_task(heartbeat_loop(aggregate_store,stop))]
    try:
        done, _ = await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        stop.set()
        await asyncio.gather(*tasks,return_exceptions=True)


def run():
    logging.basicConfig(level=logging.INFO)
    control = bootstrap_control_plane().service
    db_url = getattr(control.repo,'db_url',None)
    if not db_url:
        raise SystemExit('The Management Worker requires PostgreSQL.')
    async def main():
        stop = asyncio.Event()
        for sig in (signal.SIGINT,signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig,stop.set)
        await serve(control,DiscoverySettingsStore(db_url),DailyAggregateStore(db_url),stop)
    asyncio.run(main())


if __name__ == '__main__':
    run()
