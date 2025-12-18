from __future__ import annotations
import asyncio, json
from typing import Dict, List, Optional
from uuid import UUID

import httpx
from redis.asyncio import Redis as AsyncRedis

from dsx_connect.connectors.client import get_async_connector_client
from shared.dsx_logging import dsx_logging
from shared.models.connector_models import ConnectorInstanceModel
from dsx_connect.messaging.channels import Channel
from dsx_connect.messaging.connector_keys import ConnectorKeys  # presence/config key helper
from shared.routes import ConnectorAPI

class ConnectorsRegistry:
    def __init__(self, redis: AsyncRedis, sweep_period: int = 20):
        self._r: AsyncRedis = redis
        self._pubsub = None
        self._by_id: Dict[str, ConnectorInstanceModel] = {}
        self._lock = asyncio.Lock()
        self._tasks: List[asyncio.Task] = []
        self._sweep_period = sweep_period
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        try:
            await self._r.ping()
        except Exception as e:
            dsx_logging.warning(f"Registry: Redis unavailable at start: {e}")
            self._started = True
            return

        self._pubsub = self._r.pubsub(ignore_subscribe_messages=True)
        await self._load_from_redis()
        await self._validate_startup_connectors()

        self._tasks.append(asyncio.create_task(self._pubsub_listener(), name="connector-registry-pubsub"))
        self._tasks.append(asyncio.create_task(self._sweeper(), name="connector-registry-sweeper"))
        self._started = True
        dsx_logging.info("ConnectorsRegistry started (pub/sub + sweeper).")

    async def stop(self) -> None:
        if not self._started:
            return
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                dsx_logging.debug(f"ConnectorsRegistry stop() suppressed: {e}", exc_info=True)
        self._tasks.clear()

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(str(Channel.REGISTRY_CONNECTORS))
            except Exception:
                pass
            try:
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None

        self._started = False
        dsx_logging.info("ConnectorsRegistry stopped.")

    async def get(self, uuid: str | UUID) -> Optional[ConnectorInstanceModel]:
        uid = str(uuid)
        try:
            raw = await self._r.get(ConnectorKeys.presence(uid))
            if raw:
                text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                model = ConnectorInstanceModel(**json.loads(text))
                await self._cache_put(model)
                return model
        except Exception:
            dsx_logging.debug("Registry.get Redis error", exc_info=True)

        async with self._lock:
            return self._by_id.get(uid)

    async def list(self) -> List[ConnectorInstanceModel]:
        async with self._lock:
            return list(self._by_id.values())

    async def upsert(self, model: ConnectorInstanceModel) -> None:
        await self._cache_put(model)

    async def remove(self, uuid: str | UUID) -> None:
        async with self._lock:
            self._by_id.pop(str(uuid), None)

    async def _cache_put(self, model: ConnectorInstanceModel) -> None:
        async with self._lock:
            self._by_id[str(model.uuid)] = model

    async def _load_from_redis(self) -> None:
        found = 0
        pattern = f"{ConnectorKeys.CONNECTOR_PRESENCE_BASE}:*"
        try:
            async for key in self._r.scan_iter(pattern):
                try:
                    raw = await self._r.get(key)
                    if not raw:
                        continue
                    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    m = ConnectorInstanceModel(**json.loads(text))
                    await self._cache_put(m)
                    found += 1
                except Exception:
                    continue
            dsx_logging.info(f"ConnectorsRegistry warmed from Redis: {found} connector(s).")
        except Exception:
            dsx_logging.debug("Registry._load_from_redis error", exc_info=True)

    async def _validate_startup_connectors(self) -> None:
        """
        On startup, health-check all connectors loaded from Redis.
        Remove any that are no longer reachable and notify frontend.
        """
        items = await self.list()
        if not items:
            return

        dsx_logging.info(f"Validating {len(items)} connector(s) loaded from Redis...")

        dead_connectors = []
        alive_connectors = []

        # Check all connectors concurrently for faster startup
        async def check_connector(model: ConnectorInstanceModel):
            is_healthy = await self._check_connector_health(model)
            if is_healthy:
                alive_connectors.append(model)
                dsx_logging.debug(f"Startup validation: {model.uuid} is alive")
            else:
                dead_connectors.append(model)
                dsx_logging.info(f"Startup validation: {model.uuid} is unreachable - removing")

        # Run health checks concurrently (but with some limit to avoid overwhelming network)
        import asyncio
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent health checks

        async def bounded_check(model):
            async with semaphore:
                await check_connector(model)

        await asyncio.gather(*[bounded_check(model) for model in items])

        # Remove dead connectors from cache and Redis, and notify frontend
        for model in dead_connectors:
            await self._evict_connector(model.uuid, reason="startup_validation")

        if dead_connectors:
            dsx_logging.info(f"Startup validation removed {len(dead_connectors)} unreachable connector(s)")
        if alive_connectors:
            dsx_logging.info(f"Startup validation confirmed {len(alive_connectors)} healthy connector(s)")


    async def _evict_connector(self, uuid: str | UUID, reason: str = "health_check_failed") -> None:
        try:
            uid = str(uuid)
            await self.remove(uid)
            key = ConnectorKeys.presence(uid)
            await self._r.delete(key)
            unregister_event = {
                "type": "unregistered",
                "uuid": uid,
                "reason": reason
            }
            try:
                await self._r.publish(str(Channel.REGISTRY_CONNECTORS), json.dumps(unregister_event))
                dsx_logging.debug(f"Published unregister event for {uid} (reason: {reason})")
            except Exception as notify_error:
                dsx_logging.warning(f"Failed to notify about connector {uid} removal: {notify_error}")
        except Exception as e:
            dsx_logging.error(f"Failed to evict connector {uuid}: {e}")

    async def _pubsub_listener(self):
        if not self._pubsub:
            return
        try:
            await self._pubsub.subscribe(Channel.REGISTRY_CONNECTORS)
            dsx_logging.info(f"ConnectorsRegistry subscribed to {Channel.REGISTRY_CONNECTORS}")

            # throttle noisy error logs when Redis is flapping
            import time
            next_log_ts = 0.0

            while True:
                try:
                    msg = await self._pubsub.get_message(timeout=5.0, ignore_subscribe_messages=True)
                    if msg is None:
                        await asyncio.sleep(0.1)
                        continue

                    data = msg.get("data")
                    try:
                        text = data.decode() if isinstance(data, (bytes, bytearray)) else data
                        payload = json.loads(text)
                    except Exception:
                        continue

                    if payload.get("type") == "unregistered":
                        uid = payload.get("uuid")
                        if uid:
                            await self.remove(uid)
                            dsx_logging.info(f"Registry: removed {uid}")
                        continue

                    try:
                        model = ConnectorInstanceModel(**payload)
                        await self.upsert(model)
                        dsx_logging.info(f"Registry: upserted {model.uuid} ({getattr(model, 'name', '')})")
                    except Exception:
                        pass

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    now = time.time()
                    if now >= next_log_ts:
                        dsx_logging.warning(f"Registry pubsub disconnected: {e.__class__.__name__}: {e}")
                        next_log_ts = now + 30.0
                    await asyncio.sleep(1.0)

        finally:
            try:
                await self._pubsub.unsubscribe(Channel.REGISTRY_CONNECTORS)
            except Exception:
                pass


    async def _check_connector_health(self, model: ConnectorInstanceModel) -> bool:
        """
        Check if a connector is still responsive by calling its /readyz endpoint.
        Returns True if connector is healthy, False if unresponsive.
        """
        try:
            # Enrich with HMAC creds when available so auth-enabled connectors accept health checks
            try:
                vals = await self._r.hmget(ConnectorKeys.config(str(model.uuid)), "hmac_key_id", "hmac_secret")
                kid = vals[0].decode() if vals and isinstance(vals[0], (bytes, bytearray)) else (vals[0] if vals else None)
                sec = vals[1].decode() if vals and isinstance(vals[1], (bytes, bytearray)) else (vals[1] if vals else None)
                if kid and sec:
                    setattr(model, "hmac_key_id", kid)
                    setattr(model, "hmac_secret", sec)
            except Exception:
                pass
            async with get_async_connector_client(model) as client:
                # Use a short timeout for health checks
                response = await asyncio.wait_for(
                    client.request("GET", ConnectorAPI.HEALTHZ
                                   ),
                    timeout=5.0
                )
                response.raise_for_status()
                dsx_logging.debug(f"Connector {model.uuid} health check passed")
                return True
        except asyncio.TimeoutError:
            dsx_logging.info(f"Connector {model.uuid} health check timed out")
            return False
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            dsx_logging.info(f"Connector {model.uuid} health check failed: {type(e).__name__}")
            return False
        except Exception as e:
            dsx_logging.warning(f"Unexpected error checking connector {model.uuid} health: {e}")
            return False

    async def _pubsub_listener(self):
        if not self._pubsub:
            return
        try:
            await self._pubsub.subscribe(str(Channel.REGISTRY_CONNECTORS))
            dsx_logging.info(f"ConnectorsRegistry subscribed to {Channel.REGISTRY_CONNECTORS}")
            while True:
                try:
                    msg = await self._pubsub.get_message(timeout=5.0, ignore_subscribe_messages=True)
                    if msg is None:
                        await asyncio.sleep(0.1)
                        continue
                    data = msg.get("data")
                    try:
                        text = data.decode() if isinstance(data, (bytes, bytearray)) else data
                        payload = json.loads(text)
                    except Exception:
                        continue
                    if payload.get("type") == "unregistered":
                        uid = payload.get("uuid")
                        if uid:
                            await self.remove(uid)
                            dsx_logging.info(f"Registry: removed {uid}")
                        continue
                    try:
                        model = ConnectorInstanceModel(**payload)
                        await self.upsert(model)
                        dsx_logging.info(f"Registry: upserted {model.uuid} ({getattr(model, 'name', '')})")
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    dsx_logging.debug(f"PubSub poll error: {e}", exc_info=True)
                    await asyncio.sleep(1.0)
        finally:
            try:
                await self._pubsub.unsubscribe(str(Channel.REGISTRY_CONNECTORS))
            except Exception:
                pass

    async def _check_connector_health(self, model: ConnectorInstanceModel) -> bool:
        """
        Check if a connector is still responsive by calling its /readyz endpoint.
        Returns True if connector is healthy, False if unresponsive.
        """
        try:
            async with get_async_connector_client(model) as client:
                # Use a short timeout for health checks
                response = await asyncio.wait_for(
                    client.request("GET", ConnectorAPI.HEALTHZ
                                   ),
                    timeout=5.0
                )
                response.raise_for_status()
                dsx_logging.debug(f"Connector {model.uuid} health check passed")
                return True
        except asyncio.TimeoutError:
            dsx_logging.info(f"Connector {model.uuid} health check timed out")
            return False
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            dsx_logging.info(f"Connector {model.uuid} health check failed: {type(e).__name__}")
            return False
        except Exception as e:
            dsx_logging.warning(f"Unexpected error checking connector {model.uuid} health: {e}")
            return False

    async def _refresh_connector_ttl(self, model: ConnectorInstanceModel) -> bool:
        """
        Refresh the TTL for a healthy connector in Redis.
        Returns True if successful, False otherwise.
        """
        try:
            key = ConnectorKeys.presence(str(model.uuid))
            # Refresh the TTL - you may want to make this configurable
            ttl_seconds = 300  # 5 minutes - much more reasonable than 120s

            # Update the model's last-seen timestamp if you have one
            # model.last_seen = datetime.now(timezone.utc)  # if you add this field

            # Store the updated model with new TTL
            await self._r.setex(
                key,
                ttl_seconds,
                json.dumps(model.model_dump(), default=str)
            )
            dsx_logging.debug(f"Refreshed TTL for connector {model.uuid}")
            return True
        except Exception as e:
            dsx_logging.warning(f"Failed to refresh TTL for connector {model.uuid}: {e}")
            return False


    async def _sweeper(self):
        """
        Enhanced sweeper that health-checks connectors before evicting them.
        """
        while True:
            try:
                if not self._r:
                    await asyncio.sleep(self._sweep_period)
                    continue

                items = await self.list()
                if not items:
                    await asyncio.sleep(self._sweep_period)
                    continue

                # Check which connectors have expired in Redis
                pipe = self._r.pipeline()
                keys = [ConnectorKeys.presence(str(m.uuid)) for m in items]
                for k in keys:
                    await pipe.exists(k)
                exists = await pipe.execute()

                expired_connectors = []
                healthy_expired = []
                evicted = 0

                for model, alive in zip(items, exists):
                    if not alive:
                        expired_connectors.append(model)

                # For expired connectors, do health checks before evicting
                for model in expired_connectors:
                    dsx_logging.debug(f"Connector {model.uuid} expired in Redis, checking health...")

                    is_healthy = await self._check_connector_health(model)
                    if is_healthy:
                        # Connector is still alive, refresh its TTL
                        if await self._refresh_connector_ttl(model):
                            healthy_expired.append(model)
                            dsx_logging.info(f"Connector {model.uuid} was expired but healthy - TTL refreshed")
                        else:
                            # Failed to refresh TTL, evict it
                            await self.remove(model.uuid)
                            evicted += 1
                            dsx_logging.warning(f"Connector {model.uuid} healthy but TTL refresh failed - evicted")
                    else:
                        # Connector is unresponsive, evict it
                        await self._evict_connector(str(model.uuid), "health_check_failed")
                        evicted += 1
                        dsx_logging.info(f"Connector {model.uuid} unresponsive - evicted")

                if evicted > 0:
                    dsx_logging.info(f"Registry sweeper evicted {evicted} unresponsive connector(s)")
                if healthy_expired:
                    dsx_logging.info(f"Registry sweeper refreshed TTL for {len(healthy_expired)} healthy expired connector(s)")

            except asyncio.CancelledError:
                break
            except Exception as e:
                dsx_logging.debug("Registry sweeper error", exc_info=True)
                # keep running

            await asyncio.sleep(self._sweep_period)
