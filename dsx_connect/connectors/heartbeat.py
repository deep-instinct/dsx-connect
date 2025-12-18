import time
import httpx

from shared.dsx_logging import dsx_logging
from shared.routes import ConnectorAPI, service_url
from dsx_connect.connectors.client import get_connector_client  # current sync pool (X-API-Key); fine for now

from dsx_connect.connectors.registration import (
    register_or_refresh_connector_from_redis,
    unregister_connector_from_redis,
)

MAX_CONSECUTIVE_ERRORS = 3
SLEEP_SECONDS_DEFAULT = 30


def heartbeat_all_connectors(app, interval: int = SLEEP_SECONDS_DEFAULT) -> None:
    """
    Simple loop you already run in a background thread/process.
    - Calls connector health.
    - On 200: register/refresh presence + TTL (idempotent).
    - On 401/403: remove immediately (bad creds).
    - On other errors: strike 3 → remove.
    Never raises (just logs).
    """
    while True:
        connectors_to_check = list(getattr(app.state, "connectors", []))
        to_remove = []

        for conn in connectors_to_check:
            try:
                client = get_connector_client(conn.url)
                resp = client.get(service_url(conn.url, ConnectorAPI.HEALTHZ))
                # Raise for non-2xx so we funnel to HTTPStatusError handling
                resp.raise_for_status()

                # Healthy: (re)register + TTL refresh via one call
                register_or_refresh_connector_from_redis(conn)
                # Reset error counter if any
                if hasattr(conn, "_error_count"):
                    delattr(conn, "_error_count")

            except httpx.HTTPStatusError as http_err:
                status_code = http_err.response.status_code
                if status_code in (401, 403):
                    dsx_logging.warn(f"Heartbeat auth failed for {conn.name} ({conn.uuid}); removing.")
                    to_remove.append(conn)
                else:
                    cnt = getattr(conn, "_error_count", 0) + 1
                    setattr(conn, "_error_count", cnt)
                    dsx_logging.warn(f"Heartbeat HTTP error {status_code} for {conn.name} ({conn.uuid}) "
                                     f"[{cnt}/{MAX_CONSECUTIVE_ERRORS}]: {http_err}")
                    if cnt >= MAX_CONSECUTIVE_ERRORS:
                        to_remove.append(conn)

            except Exception as e:
                cnt = getattr(conn, "_error_count", 0) + 1
                setattr(conn, "_error_count", cnt)
                dsx_logging.warning(f"Heartbeat failed for {conn.name} ({conn.uuid}) "
                                    f"[{cnt}/{MAX_CONSECUTIVE_ERRORS}]: {e}")
                if cnt >= MAX_CONSECUTIVE_ERRORS:
                    to_remove.append(conn)

        # Remove failed connectors & send unregister events
        for conn in to_remove:
            try:
                # Best effort: unregister from Redis (publishes events)
                unregister_connector_from_redis(str(conn.uuid), name=getattr(conn, "name", None))
                # Remove from in-process list
                app.state.connectors = [c for c in getattr(app.state, "connectors", []) if c.uuid != conn.uuid]
                dsx_logging.info(f"Removed failed connector: {conn.name} ({conn.uuid})")
            except Exception as e:
                dsx_logging.error(f"Error removing connector {conn.uuid}: {e}")

        time.sleep(interval)

