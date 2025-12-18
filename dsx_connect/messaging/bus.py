from __future__ import annotations
from typing import AsyncIterator, Union, Optional, List
from time import time
import json

# Import both sync and async Redis
import redis
from redis.asyncio import Redis as AsyncRedis

from .channels import Channel
from .dlq import DeadLetterType, DLQKeys

_SUBS_ROOT = "dsx:subscribers"


class SyncBus:
    """
    Synchronous Bus implementation using synchronous Redis.
    No async overhead - true sync operations.
    """

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._r: Optional[redis.Redis] = None

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection."""
        if self._r is None:
            self._r = redis.Redis.from_url(self._redis_url, decode_responses=False)
        return self._r

    def close(self):
        """Close Redis connection."""
        if self._r:
            self._r.close()
            self._r = None

    def __enter__(self) -> "SyncBus":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ----- publish & counts -----
    def publish(self, channel: Channel | str, payload: Union[bytes, str]) -> int:
        """Synchronous publish to a given Channel or raw channel name."""
        ch = str(channel)
        if isinstance(payload, str):
            payload = payload.encode()
        return int(self.redis.publish(ch, payload))

    def publish_json(self, channel: Channel | str, data: dict) -> int:
        """Publish JSON-serializable data to a channel."""
        payload = json.dumps(data, separators=(",", ":"))
        return self.publish(channel, payload)

    def pubsub_numsub(self, channel: Channel | str) -> int:
        """Return the number of subscribers on a pub/sub channel (sync)."""
        ch = str(channel)
        res = self.redis.pubsub_numsub(ch)
        if isinstance(res, dict):
            return int(next(iter(res.values()), 0))
        if isinstance(res, list) and res:
            return int(res[0][1])
        return 0

    # ----- presence (identity list via heartbeats) -----
    def _subs_key(self, channel: Channel | str) -> str:
        return f"{_SUBS_ROOT}:{channel}"

    def subscriber_heartbeat(self, channel: Channel | str, subscriber_id: str, ttl_sec: int = 120) -> bool:
        """Send a heartbeat to indicate subscriber liveness (sync)."""
        now = int(time())
        key = self._subs_key(channel)
        self.redis.zadd(key, {subscriber_id: now})
        self.redis.expire(key, ttl_sec * 3)
        return True

    def unsubscribe(self, channel: Channel | str, subscriber_id: str) -> bool:
        """Remove a subscriber from the presence set (sync)."""
        return bool(self.redis.zrem(self._subs_key(channel), subscriber_id))

    def subscribers(self, channel: Channel | str, max_age_sec: int = 120) -> List[str]:
        """Return active subscribers on a channel (sync)."""
        now = int(time())
        cutoff = now - max_age_sec
        key = self._subs_key(channel)
        self.redis.zremrangebyscore(key, 0, cutoff - 1)
        members = self.redis.zrangebyscore(key, cutoff, now)
        return [m.decode() if isinstance(m, (bytes, bytearray)) else m for m in members]

    def subscriber_count(self, channel: Channel | str, max_age_sec: int = 120) -> int:
        """Return the count of active subscribers on a channel (sync)."""
        return len(self.subscribers(channel, max_age_sec))

    # ----- DLQ operations -----
    def _dlq_key(self, kind: DeadLetterType | str) -> str:
        """Resolve a DeadLetterType or queue key string to the fully qualified Redis key."""
        if isinstance(kind, DeadLetterType):
            return DLQKeys.key(kind)
        return str(kind)

    def dlq_enqueue(self, kind: DeadLetterType | str, item_json: str, ttl_days: Optional[int] = None) -> bool:
        """Enqueue an item into a dead letter queue (sync)."""
        key = self._dlq_key(kind)
        try:
            self.redis.rpush(key, item_json)
            if ttl_days and ttl_days > 0:
                self.redis.expire(key, ttl_days * 24 * 3600)
            return True
        except Exception:
            return False

    def dlq_peek(self, kind: DeadLetterType | str, start: int = 0, stop: int = 49) -> List[str]:
        """Return a slice of items from a DLQ without removing them (sync)."""
        key = self._dlq_key(kind)
        items = self.redis.lrange(key, start, stop)
        out: List[str] = []
        for item in items:
            if isinstance(item, (bytes, bytearray)):
                out.append(item.decode())
            else:
                out.append(item)
        return out

    def dlq_length(self, kind: DeadLetterType | str) -> int:
        """Return the length of a dead letter queue (sync)."""
        key = self._dlq_key(kind)
        return int(self.redis.llen(key))

    def dlq_exists(self, kind: DeadLetterType | str) -> bool:
        """Return True if the DLQ exists (sync)."""
        key = self._dlq_key(kind)
        return bool(self.redis.exists(key))

    def dlq_ttl(self, kind: DeadLetterType | str) -> int:
        """Return the TTL of the DLQ in seconds, or -2 if the key does not exist (sync)."""
        key = self._dlq_key(kind)
        ttl = self.redis.ttl(key)
        return int(ttl if ttl is not None else -2)

    def dlq_lpop(self, kind: DeadLetterType | str) -> Optional[str]:
        """Pop an item from the head of the DLQ (sync)."""
        key = self._dlq_key(kind)
        item = self.redis.lpop(key)
        if item is None:
            return None
        if isinstance(item, (bytes, bytearray)):
            return item.decode()
        return item

    def dlq_rpush(self, kind: DeadLetterType | str, item_json: str) -> int:
        """Push an item onto the tail of the DLQ (sync)."""
        key = self._dlq_key(kind)
        return int(self.redis.rpush(key, item_json))

    def dlq_delete(self, kind: DeadLetterType | str) -> int:
        """Delete the entire DLQ (sync). Returns number of keys removed (0 or 1)."""
        key = self._dlq_key(kind)
        return int(self.redis.delete(key))

    def dlq_lrange(self, kind: DeadLetterType | str, start: int, stop: int) -> List[str]:
        """Return a range of items from the DLQ (sync)."""
        return self.dlq_peek(kind, start, stop)


class AsyncBus:
    """Asynchronous Bus implementation using async Redis."""
    def __init__(self, client: AsyncRedis):
        self._r: AsyncRedis = client

    # ----- publish & counts -----
    async def publish(self, channel: Channel | str, payload: Union[bytes, str]) -> int:
        """Asynchronously publish to a given Channel or raw channel name."""
        ch = str(channel)
        if isinstance(payload, str):
            payload = payload.encode()
        return int(await self._r.publish(ch, payload))

    async def publish_json(self, channel: Channel | str, data: dict) -> int:
        """Publish JSON-serializable data to a channel (async)."""
        payload = json.dumps(data, separators=(",", ":"))
        return await self.publish(channel, payload)

    async def pubsub_numsub(self, channel: Channel | str) -> int:
        """Return the number of subscribers on a pub/sub channel (async)."""
        ch = str(channel)
        res = await self._r.pubsub_numsub(ch)
        if isinstance(res, dict):
            return int(next(iter(res.values()), 0))
        if isinstance(res, list) and res:
            return int(res[0][1])
        return 0

    # ----- presence (identity list via heartbeats) -----
    def _subs_key(self, channel: Channel | str) -> str:
        return f"{_SUBS_ROOT}:{channel}"

    async def subscriber_heartbeat(self, channel: Channel | str, subscriber_id: str, ttl_sec: int = 120) -> bool:
        """Send a heartbeat (async)."""
        now = int(time())
        key = self._subs_key(channel)
        await self._r.zadd(key, {subscriber_id: now})
        await self._r.expire(key, ttl_sec * 3)
        return True

    async def unsubscribe(self, channel: Channel | str, subscriber_id: str) -> bool:
        """Remove a subscriber from the presence set (async)."""
        return bool(await self._r.zrem(self._subs_key(channel), subscriber_id))

    async def subscribers(self, channel: Channel | str, max_age_sec: int = 120) -> List[str]:
        """Return active subscribers on a channel (async)."""
        now = int(time())
        cutoff = now - max_age_sec
        key = self._subs_key(channel)
        await self._r.zremrangebyscore(key, 0, cutoff - 1)
        members = await self._r.zrangebyscore(key, cutoff, now)
        return [m.decode() if isinstance(m, (bytes, bytearray)) else m for m in members]

    async def subscriber_count(self, channel: Channel | str, max_age_sec: int = 120) -> int:
        """Return the number of active subscribers (async)."""
        subs = await self.subscribers(channel, max_age_sec)
        return len(subs)

    def start_heartbeat_task(self, channel: Channel | str, subscriber_id: str, ttl_sec: int = 120):
        """Start an asynchronous heartbeat loop for a subscriber."""
        import asyncio
        interval = max(1, ttl_sec // 2)

        async def _beat():
            while True:
                await self.subscriber_heartbeat(channel, subscriber_id, ttl_sec)
                await asyncio.sleep(interval)

        return asyncio.create_task(_beat())

    # ----- async listener -----
    async def listen(self, channel: Channel | str) -> AsyncIterator[bytes]:
        """Subscribe to a Redis pub/sub channel and yield each published payload (async)."""
        p = self._r.pubsub()
        ch = str(channel)
        await p.subscribe(ch)
        try:
            async for msg in p.listen():
                if msg and msg.get("type") == "message":
                    yield msg["data"]
        finally:
            try:
                await p.unsubscribe(ch)
            finally:
                await p.close()

    # ----- DLQ operations -----
    def _dlq_key(self, kind: DeadLetterType | str) -> str:
        """Resolve a DeadLetterType or queue key string to the fully qualified Redis key."""
        if isinstance(kind, DeadLetterType):
            return DLQKeys.key(kind)
        return str(kind)

    async def dlq_enqueue(self, kind: DeadLetterType | str, item_json: str, ttl_days: Optional[int] = None) -> bool:
        """Enqueue an item into a dead letter queue (async)."""
        key = self._dlq_key(kind)
        try:
            await self._r.rpush(key, item_json)
            if ttl_days and ttl_days > 0:
                await self._r.expire(key, ttl_days * 24 * 3600)
            return True
        except Exception:
            return False

    async def dlq_peek(self, kind: DeadLetterType | str, start: int = 0, stop: int = 49) -> List[str]:
        """Return a slice of items from a DLQ without removing them (async)."""
        key = self._dlq_key(kind)
        items = await self._r.lrange(key, start, stop)
        out: List[str] = []
        for item in items:
            if isinstance(item, (bytes, bytearray)):
                out.append(item.decode())
            else:
                out.append(item)
        return out

    async def dlq_length(self, kind: DeadLetterType | str) -> int:
        """Return the length of a dead letter queue (async)."""
        key = self._dlq_key(kind)
        return int(await self._r.llen(key))

    async def dlq_exists(self, kind: DeadLetterType | str) -> bool:
        """Return True if the DLQ exists (async)."""
        key = self._dlq_key(kind)
        return bool(await self._r.exists(key))

    async def dlq_ttl(self, kind: DeadLetterType | str) -> int:
        """Return the TTL of the DLQ in seconds, or -2 if the key does not exist (async)."""
        key = self._dlq_key(kind)
        ttl = await self._r.ttl(key)
        return int(ttl if ttl is not None else -2)

    async def dlq_lpop(self, kind: DeadLetterType | str) -> Optional[str]:
        """Pop an item from the head of the DLQ (async)."""
        key = self._dlq_key(kind)
        item = await self._r.lpop(key)
        if item is None:
            return None
        if isinstance(item, (bytes, bytearray)):
            return item.decode()
        return item

    async def dlq_rpush(self, kind: DeadLetterType | str, item_json: str) -> int:
        """Push an item onto the tail of the DLQ (async)."""
        key = self._dlq_key(kind)
        return int(await self._r.rpush(key, item_json))

    async def dlq_delete(self, kind: DeadLetterType | str) -> int:
        """Delete the entire DLQ (async). Returns number of keys removed (0 or 1)."""
        key = self._dlq_key(kind)
        return int(await self._r.delete(key))

    async def dlq_lrange(self, kind: DeadLetterType | str, start: int, stop: int) -> List[str]:
        """Return a range of items from the DLQ (async)."""
        return await self.dlq_peek(kind, start, stop)

    async def close(self) -> None:
        """Close the underlying async Redis connection."""
        await self._r.close()


# Alias for backwards compatibility
Bus = AsyncBus

# ============================================================================
# Factory Functions
# ============================================================================

def create_sync_bus(redis_url: str) -> SyncBus:
    """Create a synchronous bus for Celery tasks."""
    return SyncBus(redis_url)


def create_async_bus(redis_client: AsyncRedis) -> AsyncBus:
    """Create an asynchronous bus for FastAPI routes."""
    return AsyncBus(redis_client)


# ============================================================================
# Context Managers
# ============================================================================

class sync_bus_context:
    """Context manager for one-off synchronous bus usage."""
    def __init__(self, redis_url: Optional[str] = None):
        if redis_url is None:
            from dsx_connect.config import get_config
            redis_url = str(get_config().redis_url)
        self.bus = SyncBus(redis_url)

    def __enter__(self) -> SyncBus:
        return self.bus

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.bus.close()


class async_bus_context:
    """Asynchronous context manager for one-off asynchronous bus usage."""
    def __init__(self, redis_url: Optional[str] = None):
        if redis_url is None:
            from dsx_connect.config import get_config
            redis_url = str(get_config().redis_url)
            self._client = AsyncRedis.from_url(redis_url)
        else:
            self._client = AsyncRedis.from_url(redis_url)
        self.bus = AsyncBus(self._client)

    async def __aenter__(self) -> AsyncBus:
        return self.bus

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.bus.close()


# ============================================================================
# Global Instance Management
# ============================================================================

_sync_bus_instance: Optional[SyncBus] = None


def get_sync_bus() -> SyncBus:
    """Get a shared synchronous bus instance."""
    global _sync_bus_instance
    if _sync_bus_instance is None:
        from dsx_connect.config import get_config
        _sync_bus_instance = SyncBus(str(get_config().redis_url))
    return _sync_bus_instance


def close_sync_bus():
    """Close the shared synchronous bus instance."""
    global _sync_bus_instance
    if _sync_bus_instance:
        _sync_bus_instance.close()
        _sync_bus_instance = None