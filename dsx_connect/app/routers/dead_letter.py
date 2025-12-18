from __future__ import annotations

import json
import time
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from pydantic import BaseModel


from shared.dsx_logging import dsx_logging
from shared.routes import (
    API_PREFIX_V1,
    DSXConnectAPI,
    DeadLetterPath,
    route_name,
    Action,
    route_path,
)
from dsx_connect.messaging.bus import async_bus_context
from dsx_connect.messaging.channels import Channel
from dsx_connect.messaging.dlq import DeadLetterType, DLQKeys
from dsx_connect.taskworkers.names import Tasks
from dsx_connect.taskworkers.celery_app import celery_app


# ------------------------------------------------------------------------------
# Router
# ------------------------------------------------------------------------------
router = APIRouter(
    prefix=route_path(API_PREFIX_V1, DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX),
    tags=["dead-letter"],
)

# ------------------------------------------------------------------------------
# Types & helpers
# ------------------------------------------------------------------------------
# DeadLetterType and DLQKeys are imported from dsx_connect.messaging.dlq


def default_task_for(q: DeadLetterType) -> str:
    """Return the default Celery task name to requeue items from this DLQ."""
    return {
        DeadLetterType.SCAN_REQUEST: Tasks.REQUEST,
        DeadLetterType.VERDICT_ACTION: Tasks.VERDICT,
        DeadLetterType.SCAN_RESULT: Tasks.RESULT,
    }[q]

# NOTE: direct Redis access is prohibited in this module.  All queue operations
# must go through the Bus.  Therefore, `_need_redis` is removed.
def _need_redis(request: Request):
    """
    Deprecated: Redis is no longer injected into request.app.state.  Use async_bus_context instead.
    This helper remains only to preserve backward compatibility signatures, but always raises.
    """
    raise HTTPException(status_code=503, detail="redis_unavailable")

def _json_loads_safe(s: str | bytes) -> dict[str, Any]:
    try:
        if isinstance(s, (bytes, bytearray)):
            s = s.decode("utf-8", errors="replace")
        return json.loads(s)
    except Exception:
        return {"raw": s}

async def _queue_stats(bus, kind: DeadLetterType) -> Dict[str, Any]:
    """Gather statistics about a dead letter queue via the bus."""
    try:
        exists = await bus.dlq_exists(kind)
        length = await bus.dlq_length(kind) if exists else 0
        ttl = await bus.dlq_ttl(kind) if exists else -2  # -2 no key, -1 no expiry
        return {
            "queue_name": DLQKeys.key(kind),
            "exists": bool(exists),
            "length": int(length),
            "ttl_seconds": int(ttl),
        }
    except Exception as e:
        return {"error": str(e), "queue_name": DLQKeys.key(kind)}

async def _queue_items(bus, kind: DeadLetterType, start: int, end: int) -> Dict[str, Any]:
    """Return a range of items from a dead letter queue via the bus (inclusive end)."""
    try:
        total = await bus.dlq_length(kind)
        raw_items = await bus.dlq_lrange(kind, start, end)
        items = [_json_loads_safe(x) for x in raw_items]
        return {
            "queue_name": DLQKeys.key(kind),
            "total_length": int(total),
            "returned_count": len(items),
            "start_index": start,
            "end_index": end,
            "items": items,
        }
    except Exception as e:
        return {"error": str(e), "queue_name": DLQKeys.key(kind)}

async def _notify_dlq(request: Request, event: dict) -> None:
    """Publish a DLQ-related event to the notify:dlq channel via Notifiers (async)."""
    try:
        notifiers = getattr(request.app.state, 'notifiers', None)
        if not notifiers:
            dsx_logging.warning("DLQ notify skipped: Notifiers unavailable")
            return
        await notifiers.publish_dlq_event_async(event)
    except Exception as e:
        dsx_logging.warning(f"DLQ notify failed: {e}")

async def _requeue_from_dead_letter(
        bus, kind: DeadLetterType, max_items: Optional[int], celery_task_name: str
) -> Dict[str, Any]:
    """
    Pop up to max_items from the dead letter queue and re-submit to Celery via the bus.  On Celery
    send failure, the item is pushed back to the tail of the queue.
    """
    requeued = 0
    failed = 0
    queue_name = DLQKeys.key(kind)
    try:
        to_process = await bus.dlq_length(kind)
        if not to_process:
            return {"queue_name": queue_name, "requeued_count": 0, "remaining_count": 0, "failed_count": 0}

        limit = to_process if max_items is None else min(to_process, int(max_items))
        for _ in range(limit):
            payload = await bus.dlq_lpop(kind)
            if payload is None:
                break
            dlq_item = _json_loads_safe(payload)
            try:
                # Extract the original task arguments from the DLQ item payload
                if "payload" in dlq_item:
                    if "scan_request" in dlq_item["payload"] and "verdict" not in dlq_item["payload"]:
                        # For scan_request tasks: args=[scan_request_dict]
                        task_args = [dlq_item["payload"]["scan_request"]]
                    elif "scan_request" in dlq_item["payload"] and "verdict" in dlq_item["payload"]:
                        # For verdict/result tasks
                        task_args = [dlq_item["payload"]["scan_request"], dlq_item["payload"]["verdict"]]
                        if "item_action" in dlq_item["payload"]:
                            task_args.append(dlq_item["payload"]["item_action"])
                    else:
                        task_args = [dlq_item.get("payload", dlq_item)]
                else:
                    task_args = [dlq_item]
                # Add chain metadata as kwargs if available
                task_kwargs = {}
                if "chain" in dlq_item and dlq_item["chain"].get("scan_request_task_id"):
                    task_kwargs["scan_request_task_id"] = dlq_item["chain"]["scan_request_task_id"]
                # Send to Celery
                celery_app.send_task(celery_task_name, args=task_args, kwargs=task_kwargs)
                requeued += 1
                dsx_logging.info(
                    f"Requeued DLQ item to {celery_task_name}: "
                    f"{dlq_item.get('chain', {}).get('current_task_id', 'unknown')}"
                )
            except Exception as e:
                failed += 1
                dsx_logging.error(f"Failed to requeue DLQ item: {e}", exc_info=True)
                try:
                    # Put it back at the end of the queue
                    await bus.dlq_rpush(kind, payload)
                except Exception:
                    dsx_logging.error(f"Failed to restore DLQ item after Celery error: {e}")
        remaining = await bus.dlq_length(kind)
        return {
            "queue_name": queue_name,
            "requeued_count": requeued,
            "remaining_count": remaining,
            "failed_count": failed,
        }
    except Exception as e:
        dsx_logging.error(f"Error in _requeue_from_dead_letter: {e}", exc_info=True)
        return {"error": str(e), "queue_name": queue_name}

async def _clear_dead_letter_queue(bus, kind: DeadLetterType) -> Dict[str, Any]:
    """Remove all items from a dead letter queue via the bus."""
    queue_name = DLQKeys.key(kind)
    try:
        removed = await bus.dlq_delete(kind)
        return {"queue_name": queue_name, "cleared_count": int(removed)}
    except Exception as e:
        return {"error": str(e), "queue_name": queue_name}

# ------------------------------------------------------------------------------
# Response models
# ------------------------------------------------------------------------------
class QueueStatsResponse(BaseModel):
    queue_name: str
    queue_type: str
    length: int
    ttl_seconds: int
    exists: bool
    sample_items: Optional[list[dict[str, Any]]] = None

class DeadLetterSummaryResponse(BaseModel):
    total_items: int
    active_queues: int
    queues: dict[str, QueueStatsResponse]

class RequeueResponse(BaseModel):
    success: bool
    queue_type: str
    queue_name: str
    requeued_count: int
    remaining_count: int
    failed_count: Optional[int] = 0

class ClearQueueResponse(BaseModel):
    success: bool
    queue_type: str
    queue_name: str
    cleared_count: int

class DeadLetterItemsResponse(BaseModel):
    queue_type: str
    queue_name: str
    total_length: int
    returned_count: int
    start_index: int
    end_index: int
    items: list[dict[str, Any]]

class RequeueAllDetail(BaseModel):
    queue_type: str
    queue_name: str
    requeued_count: int
    remaining_count: int

class RequeueAllResponse(BaseModel):
    success: bool
    results: list[RequeueAllDetail]

# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@router.get(
    route_path(DeadLetterPath.STATS),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.STATS, Action.STATS),
    response_model=DeadLetterSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_dead_letter_stats(request: Request):
    """Get summary stats for all dead letter queues."""
    try:
        detailed: Dict[str, QueueStatsResponse] = {}
        total = 0
        active = 0
        async with async_bus_context() as bus:
            for qtype in DeadLetterType:
                stats = await _queue_stats(bus, qtype)
                if "error" in stats:
                    dsx_logging.error(f"Stats error for {qtype.value}: {stats['error']}")
                    detailed[qtype.value] = QueueStatsResponse(
                        queue_name=DLQKeys.key(qtype),
                        queue_type=qtype.value,
                        length=0,
                        ttl_seconds=-1,
                        exists=False,
                    )
                    continue
                length = stats.get("length", 0)
                resp = QueueStatsResponse(
                    queue_name=DLQKeys.key(qtype),
                    queue_type=qtype.value,
                    length=int(length),
                    ttl_seconds=int(stats.get("ttl_seconds", -1)),
                    exists=bool(stats.get("exists", True)),
                )
                if length > 0:
                    try:
                        sample = await _queue_items(bus, qtype, 0, 2)  # show up to 3
                        resp.sample_items = sample.get("items", [])
                    except Exception as e:
                        dsx_logging.warning(f"Sample items failed for {qtype.value}: {e}")
                        resp.sample_items = []
                    active += 1
                    total += int(length)
                detailed[qtype.value] = resp
        return DeadLetterSummaryResponse(total_items=total, active_queues=active, queues=detailed)
    except Exception as e:
        dsx_logging.error(f"Failed to get dead letter stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get dead letter stats: {e}")

@router.get(
    route_path(DeadLetterPath.STATS_ONE),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.STATS_ONE, Action.GET),
    response_model=QueueStatsResponse,
)
async def get_queue_specific_stats(
        request: Request,
        queue_type: DeadLetterType = Path(...),
) -> QueueStatsResponse:
    """Get detailed stats for a specific dead letter queue type via the Bus."""
    try:
        async with async_bus_context() as bus:
            # Use bus to gather stats
            stats = await _queue_stats(bus, queue_type)
            if "error" in stats:
                raise HTTPException(status_code=500, detail=stats["error"])

            length = int(stats.get("length", 0))
            resp = QueueStatsResponse(
                queue_name=DLQKeys.key(queue_type),
                queue_type=queue_type.value,
                length=length,
                ttl_seconds=int(stats.get("ttl_seconds", -1)),
                exists=bool(stats.get("exists", True)),
            )
            if length > 0:
                sample = await _queue_items(bus, queue_type, 0, 4)  # Show up to 5 items
                resp.sample_items = sample.get("items", [])
            return resp
    except HTTPException:
        raise
    except Exception as e:
        dsx_logging.error(f"Failed to get stats for {queue_type.value}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}")

@router.get(
    route_path(DeadLetterPath.ITEMS),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.ITEMS, Action.LIST),
    response_model=DeadLetterItemsResponse,
)
async def get_dead_letter_items(
        request: Request,
        queue_type: DeadLetterType = Path(...),
        start: int = Query(0, ge=0),
        end: int = Query(10, ge=0, le=100),
) -> DeadLetterItemsResponse:
    """Get a range of items from a specific dead letter queue via the Bus."""
    try:
        if end < start:
            raise HTTPException(status_code=400, detail="End index must be >= start index")
        async with async_bus_context() as bus:
            data = await _queue_items(bus, queue_type, start, end)
            if "error" in data:
                raise HTTPException(status_code=500, detail=data["error"])
            return DeadLetterItemsResponse(
                queue_type=queue_type.value,
                queue_name=data.get("queue_name", DLQKeys.key(queue_type)),
                total_length=int(data.get("total_length", 0)),
                returned_count=int(data.get("returned_count", 0)),
                start_index=int(data.get("start_index", start)),
                end_index=int(data.get("end_index", end)),
                items=data.get("items", []),
            )
    except HTTPException:
        raise
    except Exception as e:
        dsx_logging.error(f"Failed to get items from {queue_type.value}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get items: {e}")

@router.post(
    route_path(DeadLetterPath.REQUEUE),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.REQUEUE, Action.REQUEUE),
    response_model=RequeueAllResponse,
)
async def requeue_all_dead_letters(request: Request) -> RequeueAllResponse:
    """Requeue all items from all dead letter queues back to their original tasks via the Bus."""
    ok = True
    results: List[RequeueAllDetail] = []
    try:
        async with async_bus_context() as bus:
            for qtype in DeadLetterType:
                celery_task = str(default_task_for(qtype))
                try:
                    res = await _requeue_from_dead_letter(bus, qtype, max_items=None, celery_task_name=celery_task)
                    if "error" in res:
                        ok = False
                        dsx_logging.error(f"Error requeueing {qtype.value}: {res['error']}")
                        results.append(RequeueAllDetail(queue_type=qtype.value, queue_name=DLQKeys.key(qtype), requeued_count=0, remaining_count=res.get("remaining_count", 0)))
                    else:
                        results.append(RequeueAllDetail(queue_type=qtype.value, queue_name=DLQKeys.key(qtype), requeued_count=int(res.get("requeued_count", 0)), remaining_count=int(res.get("remaining_count", 0))))
                        await _notify_dlq(request, {"type": "requeue", "queue_type": qtype.value, "queue_name": DLQKeys.key(qtype), "timestamp": time.time()})
                except Exception as e:
                    ok = False
                    dsx_logging.error(f"Exception requeueing {qtype.value}: {e}", exc_info=True)
                    results.append(RequeueAllDetail(queue_type=qtype.value, queue_name=DLQKeys.key(qtype), requeued_count=0, remaining_count=0))
        return RequeueAllResponse(success=ok, results=results)
    except Exception as e:
        dsx_logging.error(f"Failed to requeue all dead letters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to requeue all dead letters: {e}")

@router.post(
    route_path(DeadLetterPath.REQUEUE_ONE),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.REQUEUE_ONE, Action.REQUEUE),
    response_model=RequeueResponse,
)
async def requeue_specific_queue(
        request: Request,
        queue_type: DeadLetterType = Path(...),
        max_items: int = Query(100, ge=1, le=1000),
        target_task: Optional[str] = Query(None),
) -> RequeueResponse:
    """Requeue up to max_items items from a specific dead letter queue via the Bus."""
    try:
        async with async_bus_context() as bus:
            celery_task = target_task or str(default_task_for(queue_type))
            res = await _requeue_from_dead_letter(bus, queue_type, max_items=max_items, celery_task_name=celery_task)
            if "error" in res:
                raise HTTPException(status_code=500, detail=res["error"])
            # Notify UI about requeue
            await _notify_dlq(
                request,
                {
                    "type": "requeue",
                    "queue_type": queue_type.value,
                    "queue_name": DLQKeys.key(queue_type),
                    "requeued_count": int(res.get("requeued_count", 0)),
                    "timestamp": time.time(),
                },
            )
            return RequeueResponse(
                success=True,
                queue_type=queue_type.value,
                queue_name=DLQKeys.key(queue_type),
                requeued_count=int(res.get("requeued_count", 0)),
                remaining_count=int(res.get("remaining_count", 0)),
                failed_count=int(res.get("failed_count", 0)),
            )
    except HTTPException:
        raise
    except Exception as e:
        dsx_logging.error(f"Failed to requeue {queue_type.value}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to requeue: {e}")

@router.delete(
    route_path(DeadLetterPath.CLEAR_ONE),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.CLEAR_ONE, Action.CLEAR),
    response_model=ClearQueueResponse,
)
async def clear_specific_queue(
        request: Request,
        queue_type: DeadLetterType = Path(...),
) -> ClearQueueResponse:
    """Clear all items from a specific dead letter queue via the Bus."""
    try:
        async with async_bus_context() as bus:
            res = await _clear_dead_letter_queue(bus, queue_type)
            if "error" in res:
                raise HTTPException(status_code=500, detail=res["error"])
            await _notify_dlq(
                request,
                {
                    "type": "clear",
                    "queue_type": queue_type.value,
                    "queue_name": DLQKeys.key(queue_type),
                    "timestamp": time.time(),
                },
            )
            return ClearQueueResponse(
                success=True,
                queue_type=queue_type.value,
                queue_name=DLQKeys.key(queue_type),
                cleared_count=int(res.get("cleared_count", 0)),
            )
    except HTTPException:
        raise
    except Exception as e:
        dsx_logging.error(f"Failed to clear {queue_type.value}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear queue: {e}")

@router.delete(
    route_path(DeadLetterPath.CLEAR),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.CLEAR, Action.CLEAR),
    response_model=list[ClearQueueResponse],
)
async def clear_all_dead_letter_queues(request: Request) -> list[ClearQueueResponse]:
    """Clear all items from all dead letter queues via the Bus."""
    out: list[ClearQueueResponse] = []
    try:
        async with async_bus_context() as bus:
            for qtype in DeadLetterType:
                try:
                    res = await _clear_dead_letter_queue(bus, qtype)
                    if "error" in res:
                        dsx_logging.error(f"Failed to clear {qtype.value}: {res['error']}")
                        continue
                    out.append(
                        ClearQueueResponse(
                            success=True,
                            queue_type=qtype.value,
                            queue_name=DLQKeys.key(qtype),
                            cleared_count=int(res.get("cleared_count", 0)),
                        )
                    )
                    await _notify_dlq(
                        request,
                        {
                            "type": "clear",
                            "queue_type": qtype.value,
                            "queue_name": DLQKeys.key(qtype),
                            "timestamp": time.time(),
                        },
                    )
                except Exception as e:
                    dsx_logging.error(f"Failed to clear {qtype.value}: {e}")
                    continue
        if not out:
            raise HTTPException(status_code=500, detail="Failed to clear any queues")
        dsx_logging.warning(f"Cleared all dead letter queues: {[r.queue_type for r in out]}")
        return out
    except HTTPException:
        raise
    except Exception as e:
        dsx_logging.error(f"Failed to clear all dead letter queues: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear queues: {e}")

@router.get(
    route_path(DeadLetterPath.HEALTH),
    name=route_name(DSXConnectAPI.ADMIN_DEAD_LETTER_QUEUE_PREFIX, DeadLetterPath.HEALTH, Action.HEALTH),
    status_code=status.HTTP_200_OK,
)
async def dead_letter_health_check(request: Request):
    """Health check endpoint for the dead letter queue system using the Bus."""
    try:
        async with async_bus_context() as bus:
            # Attempt to ping Redis via the underlying client
            try:
                await bus._r.ping()
                redis_connected = True
            except Exception:
                redis_connected = False
            total = 0
            if redis_connected:
                for qtype in DeadLetterType:
                    stats = await _queue_stats(bus, qtype)
                    if "error" not in stats:
                        total += int(stats.get("length", 0))
            status_text = "healthy" if redis_connected else "unhealthy"
            return {
                "status": status_text,
                "redis_connected": redis_connected,
                "total_dead_letter_items": total,
                "available_queues": [q.value for q in DeadLetterType],
            }
    except Exception as e:
        dsx_logging.error(f"Dead letter health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "redis_connected": False,
        }
