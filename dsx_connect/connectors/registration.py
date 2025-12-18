from __future__ import annotations
import json
from typing import Optional, Tuple, Union
from uuid import UUID
from fastapi import Request
from redis.asyncio import Redis as AsyncRedis

from dsx_connect.messaging.notifiers import Notifiers
from dsx_connect.messaging.bus import Bus, SyncBus
from dsx_connect.messaging.channels import Channel
from dsx_connect.messaging.connector_keys import ConnectorKeys
from shared.models.connector_models import ConnectorInstanceModel
from shared.dsx_logging import dsx_logging

DEFAULT_TTL = 120  # seconds (non-dev default)

def _effective_ttl(default_ttl: int | None = None) -> int:
    """Resolve the TTL based on app environment.

    Dev environment: use a longer TTL (600s) to tolerate laptop sleep.
    Other environments: use provided default (or 120s).
    """
    try:
        from dsx_connect.config import get_config, AppEnv  # local import to avoid circulars at import time
        cfg = get_config()
        if getattr(cfg, "app_env", None) == AppEnv.dev:
            return 600
    except Exception:
        pass
    return int(default_ttl or DEFAULT_TTL)

# ---------------------------------------------------------------------------
# Note on registration functions:
#
# This module exposes both asynchronous and synchronous helper functions for
# managing connector presence in Redis and publishing registration events.
#
# * ``register_or_refresh_connector`` and ``unregister_connector`` are
#   asynchronous and accept a FastAPI ``Request`` to fetch the shared
#   services (Redis, Bus, Notifiers) from ``app.state``.  These should be
#   used from within FastAPI routes.
#
# * ``register_or_refresh_connector_from_redis`` and
#   ``unregister_connector_from_redis`` are synchronous helpers intended for
#   environments outside of FastAPI (e.g., background heartbeats).  They use
#   a synchronous Redis client and ``SyncBus`` to perform the same work.
#   These functions do **not** emit UI notifications, only internal
#   registration bus events.
#
# See ``heartbeat.py`` for usage.

def _get_services(request: Request) -> tuple[Optional[AsyncRedis], Optional[Bus], Optional[Notifiers]]:
    app = request.app
    return (
        getattr(app.state, "redis", None),
        getattr(app.state, "bus", None),
        getattr(app.state, "notifiers", None),
    )

async def register_or_refresh_connector(
        request: Request,
        conn: ConnectorInstanceModel,
        ttl: int | None = None,
) -> Tuple[bool, str]:
    """
    Upsert presence for a connector and broadcast:
      - full model on REGISTRY_CONNECTORS (internal)
      - compact envelope on NOTIFY_CONNECTORS (UI)
    Returns (ok, 'registered'|'refreshed'|'unavailable').
    """
    r, bus, notifiers = _get_services(request)
    if r is None:
        try:
            from dsx_connect.config import get_config  # local import to avoid cycles
            cfg = get_config()
            dsx_logging.warning(
                f"Registry unavailable; no async Redis client provided (DSXCONNECT_REDIS_URL={cfg.redis_url})"
            )
        except Exception:
            dsx_logging.warning("Registry unavailable; no async Redis client provided")
        return False, "unavailable"

    key = ConnectorKeys.presence(str(conn.uuid))
    model_json = json.dumps(conn.model_dump(mode="json"), separators=(",", ":"))
    ttl_sec = _effective_ttl(ttl)

    try:
        is_new = await r.set(name=key, value=model_json, ex=ttl_sec, nx=True)
        if not is_new:
            # Existing connector; refresh payload + TTL so updated fields (url, status, etc.)
            await r.set(name=key, value=model_json, ex=ttl_sec)

        # Internal bus: full payload for registry cache
        if bus is not None:
            await bus.publish(Channel.REGISTRY_CONNECTORS, model_json)

        # Notify SSE endpoints...
        if notifiers is not None:
            await notifiers.publish_connector_notify(
                event=("registered" if is_new else "refreshed"),
                uuid=str(conn.uuid),
                name=conn.name,
                url=conn.url,
            )
        return True, ("registered" if is_new else "refreshed")
    except Exception as e:
        dsx_logging.error(f"Redis operation failed for connector {conn.uuid}: {e}")
        return False, "unavailable"

async def unregister_connector(
        request: Request,
        uuid: Union[str, UUID],
        name: Optional[str] = None,
        url: Optional[str] = None,
) -> bool:
    """Delete presence and publish an 'unregistered' to both buses."""
    r, bus, notifiers = _get_services(request)
    if r is None:
        try:
            from dsx_connect.config import get_config
            cfg = get_config()
            dsx_logging.warning(
                f"Registry unavailable; no async Redis client provided (DSXCONNECT_REDIS_URL={cfg.redis_url})"
            )
        except Exception:
            dsx_logging.warning("Registry unavailable; no async Redis client provided")
        return False

    uid = str(uuid)
    try:
        await r.delete(ConnectorKeys.presence(uid))

        # Internal bus: lightweight envelope understood by ConnectorsRegistry
        envelope = json.dumps({"type": "unregistered", "uuid": uid, "name": name}, separators=(",", ":"))
        if bus is not None:
            await bus.publish(Channel.REGISTRY_CONNECTORS, envelope)

        # UI bus
        if notifiers is not None:
            await notifiers.publish_connector_notify(event="unregistered", uuid=uid, name=name or "", url=url or "")

        return True
    except Exception as e:
        dsx_logging.error(f"Redis operation failed during unregister {uid}: {e}")
        return False


# ---------------------------------------------------------------------------
# Synchronous registration helpers for heartbeat threads
# ---------------------------------------------------------------------------
import redis  # imported here to avoid mandatory dependency for async-only use cases
from dsx_connect.config import get_config


def _get_sync_services() -> tuple[redis.Redis | None, SyncBus | None]:
    """Retrieve a synchronous Redis client and SyncBus based on current config.

    This helper reads the Redis URL from the dsx_connect configuration and
    returns a tuple ``(redis_client, sync_bus)``.  If the configuration
    cannot be loaded, ``(None, None)`` is returned.

    Returns:
        A tuple of (redis.Redis | None, SyncBus | None).
    """
    try:
        cfg = get_config()
        redis_url = str(cfg.redis_url)
    except Exception:
        return None, None
    try:
        r = redis.Redis.from_url(redis_url, decode_responses=False)
    except Exception:
        r = None
    try:
        bus = SyncBus(redis_url)
    except Exception:
        bus = None
    return r, bus


def register_or_refresh_connector_from_redis(
        conn: ConnectorInstanceModel,
        ttl: int | None = None,
) -> tuple[bool, str]:
    """
    Synchronous variant of ``register_or_refresh_connector`` for use outside of
    FastAPI request context (e.g., heartbeat threads).  It updates the
    connector's presence key in Redis and publishes a full model payload to
    the internal registry bus.

    UI notifications are **not** emitted by this function.

    Args:
        conn: The connector instance to register or refresh.
        ttl: Time-to-live for the presence key in seconds.

    Returns:
        A tuple ``(ok, status)`` where ``ok`` is True if the operation
        succeeded and ``status`` is ``'registered'``, ``'refreshed'`` or
        ``'unavailable'``.
    """
    r, bus = _get_sync_services()
    if r is None:
        dsx_logging.warning("Registry unavailable; no sync Redis client provided")
        return False, "unavailable"

    key = ConnectorKeys.presence(str(conn.uuid))
    model_json = json.dumps(conn.model_dump(mode="json"), separators=(",", ":"))
    ttl_eff = _effective_ttl(ttl)
    try:
        is_new = r.set(name=key, value=model_json, ex=ttl_eff, nx=True)
        if not is_new:
            # Refresh TTL if existing
            r.expire(key, ttl_eff)

        # Publish full payload on the internal registry bus
        if bus is not None:
            bus.publish(Channel.REGISTRY_CONNECTORS, model_json)

        return True, ("registered" if is_new else "refreshed")
    except Exception as e:
        dsx_logging.error(f"Sync Redis operation failed for connector {conn.uuid}: {e}")
        return False, "unavailable"
    finally:
        # Close the bus and redis connection (they are lazily instantiated)
        try:
            if bus is not None:
                bus.close()
        except Exception:
            pass
        try:
            if r is not None:
                r.close()
        except Exception:
            pass


def unregister_connector_from_redis(
        uuid: Union[str, UUID],
        name: Optional[str] = None,
        ttl: int = DEFAULT_TTL,
) -> bool:
    """
    Synchronous variant of ``unregister_connector`` for use outside of FastAPI.
    Deletes the connector's presence key from Redis and publishes an
    ``unregistered`` envelope to the internal registry bus.  UI notifications
    are not emitted by this function.

    Args:
        uuid: UUID of the connector to unregister (string or UUID).
        name: Optional connector name, included in the unregister envelope.
        ttl: TTL parameter is ignored here but kept for backward compatibility.

    Returns:
        True if the unregister operation succeeded, False otherwise.
    """
    uid = str(uuid)
    r, bus = _get_sync_services()
    if r is None:
        dsx_logging.warning("Registry unavailable; no sync Redis client provided")
        return False
    try:
        # Delete presence key
        r.delete(ConnectorKeys.presence(uid))

        # Publish an unregister envelope to the registry bus
        envelope = json.dumps({"type": "unregistered", "uuid": uid, "name": name}, separators=(",", ":"))
        if bus is not None:
            bus.publish(Channel.REGISTRY_CONNECTORS, envelope)
        return True
    except Exception as e:
        dsx_logging.error(f"Sync Redis operation failed during unregister {uid}: {e}")
        return False
    finally:
        try:
            if bus is not None:
                bus.close()
        except Exception:
            pass
        try:
            if r is not None:
                r.close()
        except Exception:
            pass
