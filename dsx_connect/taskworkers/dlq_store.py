import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder

from dsx_connect.messaging.bus import sync_bus_context, async_bus_context
from dsx_connect.messaging.dlq import DeadLetterType

@dataclass(frozen=True)
class DeadLetterItem:
    queue: DeadLetterType
    reason: str
    error_details: str
    retry_count: int

    idempotency_key: str
    payload: Dict[str, Any]

    # 👇 chain metadata (first-class)
    scan_request_task_id: str         # root that started the chain
    current_task_id: str              # this failing task
    upstream_task_id: Optional[str] = None  # optional: the task that scheduled this one
    meta: Optional[Dict[str, Any]] = None

def _hash(obj: Dict[str, Any]) -> str:
    # Ensure all non-JSON-native types (UUID, datetime, etc.) are made serializable
    safe = jsonable_encoder(obj)
    return hashlib.sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

def _to_msg(item: DeadLetterItem) -> Dict[str, Any]:
    # same as you have now, but JSON-safe (UUID, datetime, etc.)
    return {
        "queue": item.queue,
        "reason": item.reason,
        "error_details": item.error_details,
        "retry_count": item.retry_count,
        "idempotency_key": item.idempotency_key,
        "payload": jsonable_encoder(item.payload),
        "meta": jsonable_encoder(item.meta) if item.meta else {},
        "chain": {
            "scan_request_task_id": item.scan_request_task_id,
            "current_task_id": item.current_task_id,
            "upstream_task_id": item.upstream_task_id,
        },
    }

def _to_wire(item: DeadLetterItem) -> str:
    # Redis wants str/bytes; keep it compact
    return json.dumps(_to_msg(item), separators=(",", ":"), ensure_ascii=False)


# ---------- factories (no magic strings) ----------
def make_scan_request_dlq_item(
        scan_request: Dict[str, Any], *,
        error: Exception, reason: str,
        scan_request_task_id: str, current_task_id: str,
        retry_count: int, upstream_task_id: Optional[str] = None,
) -> DeadLetterItem:
    payload = {"scan_request": scan_request}
    return DeadLetterItem(
        queue=DeadLetterType.SCAN_REQUEST,
        reason=reason,
        error_details=repr(error),
        retry_count=retry_count,
        scan_request_task_id=scan_request_task_id,
        current_task_id=current_task_id,
        upstream_task_id=upstream_task_id,
        idempotency_key=_hash(payload),
        payload=payload,
    )

def make_verdict_action_dlq_item(
        scan_request: Dict[str, Any], verdict: Dict[str, Any], *,
        error: Exception, reason: str,
        scan_request_task_id: str, current_task_id: str,
        retry_count: int, upstream_task_id: Optional[str] = None,
) -> DeadLetterItem:
    payload = {"scan_request": scan_request, "verdict": verdict}
    return DeadLetterItem(
        queue=DeadLetterType.VERDICT_ACTION,
        reason=reason,
        error_details=repr(error),
        retry_count=retry_count,
        scan_request_task_id=scan_request_task_id,
        current_task_id=current_task_id,
        upstream_task_id=upstream_task_id,
        idempotency_key=_hash(payload),
        payload=payload,
    )

def make_scan_result_dlq_item(
        scan_request: Dict[str, Any], verdict: Dict[str, Any], item_action: Dict[str, Any], *,
        error: Exception, reason: str,
        scan_request_task_id: str, current_task_id: str,
        retry_count: int, upstream_task_id: Optional[str] = None,
) -> DeadLetterItem:
    payload = {"scan_request": scan_request, "verdict": verdict, "item_action": item_action}
    return DeadLetterItem(
        queue=DeadLetterType.SCAN_RESULT,
        reason=reason,
        error_details=repr(error),
        retry_count=retry_count,
        scan_request_task_id=scan_request_task_id,
        current_task_id=current_task_id,
        upstream_task_id=upstream_task_id,
        idempotency_key=_hash(payload),
        payload=payload,
    )

# ---------- true SYNC via Bus ----------
def enqueue_scan_request_dlq_sync(item: DeadLetterItem) -> None:
    """Synchronously enqueue a scan_request dead-letter item into the DLQ."""
    with sync_bus_context() as bus:
        # Use the bus DLQ API; queue is a DeadLetterType
        bus.dlq_enqueue(item.queue, _to_wire(item))

def enqueue_verdict_action_dlq_sync(item: DeadLetterItem) -> None:
    """Synchronously enqueue a verdict_action dead-letter item into the DLQ."""
    with sync_bus_context() as bus:
        bus.dlq_enqueue(item.queue, _to_wire(item))

def enqueue_scan_result_dlq_sync(item: DeadLetterItem) -> None:
    """Synchronously enqueue a scan_result dead-letter item into the DLQ."""
    with sync_bus_context() as bus:
        bus.dlq_enqueue(item.queue, _to_wire(item))

# ---------- true ASYNC via Bus ----------
async def enqueue_scan_request_dlq_async(item: DeadLetterItem) -> None:
    """Asynchronously enqueue a scan_request dead-letter item into the DLQ."""
    async with async_bus_context() as bus:
        await bus.dlq_enqueue(item.queue, _to_wire(item))


async def enqueue_verdict_action_dlq_async(item: DeadLetterItem) -> None:
    """Asynchronously enqueue a verdict_action dead-letter item into the DLQ."""
    async with async_bus_context() as bus:
        await bus.dlq_enqueue(item.queue, _to_wire(item))


async def enqueue_scan_result_dlq_async(item: DeadLetterItem) -> None:
    """Asynchronously enqueue a scan_result dead-letter item into the DLQ."""
    async with async_bus_context() as bus:
        await bus.dlq_enqueue(item.queue, _to_wire(item))

