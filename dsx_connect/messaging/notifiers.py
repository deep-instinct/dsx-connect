from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator, Optional
import json, time
from fastapi.encoders import jsonable_encoder
from .channels import Channel
from .bus import AsyncBus, SyncBus


@dataclass(slots=True)
class Notifiers:
    """
    Dual-mode notifier supporting both async and sync Redis buses.

    - In FastAPI (async), construct with AsyncBus and call the async methods.
    - In Celery (sync), construct with SyncBus and call the sync methods.

    No cross-wrapping between sync/async paths to avoid overhead.
    """
    _abus: Optional[AsyncBus] = None
    _sbus: Optional[SyncBus] = None

    def __init__(self, bus: AsyncBus | SyncBus):
        if isinstance(bus, AsyncBus):
            self._abus = bus
        elif isinstance(bus, SyncBus):
            self._sbus = bus
        else:
            raise TypeError("Notifiers requires AsyncBus or SyncBus")

    # -------- async publish ---------------------------------------------------
    async def publish_scan_results_async(self, scan_result) -> int:
        if not self._abus:
            raise RuntimeError("Async bus not configured")
        payload = json.dumps(jsonable_encoder(scan_result), separators=(",", ":"))
        return await self._abus.publish(Channel.NOTIFY_SCAN_RESULT, payload)

    async def publish_connector_notify_async(self, *, event: str, uuid: str, name: str, url: str) -> int:
        if not self._abus:
            raise RuntimeError("Async bus not configured")
        payload = json.dumps(
            {"type": event, "uuid": uuid, "name": name, "url": url, "ts": time.time()},
            separators=(",", ":"),
        )
        return await self._abus.publish(Channel.NOTIFY_CONNECTORS, payload)

    # Backwards-compat async names
    async def publish_scan_results(self, scan_result) -> int:
        return await self.publish_scan_results_async(scan_result)

    async def publish_connector_notify(self, *, event: str, uuid: str, name: str, url: str) -> int:
        return await self.publish_connector_notify_async(event=event, uuid=uuid, name=name, url=url)

    # -------- sync publish ----------------------------------------------------
    def publish_scan_results_sync(self, scan_result) -> int:
        if not self._sbus:
            raise RuntimeError("Sync bus not configured")
        payload = json.dumps(jsonable_encoder(scan_result), separators=(",", ":"))
        return self._sbus.publish(Channel.NOTIFY_SCAN_RESULT, payload)

    def publish_connector_notify_sync(self, *, event: str, uuid: str, name: str, url: str) -> int:
        if not self._sbus:
            raise RuntimeError("Sync bus not configured")
        payload = json.dumps(
            {"type": event, "uuid": uuid, "name": name, "url": url, "ts": time.time()},
            separators=(",", ":"),
        )
        return self._sbus.publish(Channel.NOTIFY_CONNECTORS, payload)

    # -------- async subscribe (yields parsed JSON dicts) ----------------------
    async def subscribe_scan_results(self) -> AsyncIterator[dict]:
        if not self._abus:
            raise RuntimeError("Async bus not configured")
        async for raw in self._abus.listen(Channel.NOTIFY_SCAN_RESULT):
            try:
                yield json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
            except Exception:
                continue  # drop bad frames

    async def subscribe_connector_notify(self) -> AsyncIterator[dict]:
        if not self._abus:
            raise RuntimeError("Async bus not configured")
        async for raw in self._abus.listen(Channel.NOTIFY_CONNECTORS):
            try:
                yield json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
            except Exception:
                continue

    # -------- DLQ notifications ---------------------------------------------
    async def publish_dlq_event_async(self, event: dict) -> int:
        if not self._abus:
            raise RuntimeError("Async bus not configured")
        return await self._abus.publish_json(Channel.NOTIFY_DLQ, event)

    def publish_dlq_event_sync(self, event: dict) -> int:
        if not self._sbus:
            raise RuntimeError("Sync bus not configured")
        return self._sbus.publish_json(Channel.NOTIFY_DLQ, event)
