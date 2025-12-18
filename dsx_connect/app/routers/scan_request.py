from typing import Optional, Literal, Any
import time
import uuid as _uuid

from celery.result import AsyncResult
from fastapi import APIRouter, Request, Response, Header, Path
from celery.exceptions import CeleryError, TimeoutError as CeleryTimeoutError
from kombu.exceptions import OperationalError as BrokerOperationalError
from pydantic import BaseModel
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from shared.dsx_logging import dsx_logging
from dsx_connect.app.auth_hmac_inbound import require_dsx_hmac_inbound
from shared.routes import (API_PREFIX_V1, DSXConnectAPI, ScanPath,
                           api_path, Action, route_name, route_path)
from shared.models.connector_models import ScanRequestModel
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues
from shared.models.status_responses import StatusResponse, StatusResponseEnum


class ScanRequestStatus(BaseModel):
    task_id: str
    state: Literal["PENDING", "RECEIVED", "STARTED", "RETRY", "FAILURE", "SUCCESS"]
    status: StatusResponseEnum  # SUCCESS/ERROR for your API contract
    result: Optional[Any] = None  # include only on SUCCESS (if you store a result)
    error: Optional[str] = None  # include only on FAILURE


router = APIRouter(prefix=route_path(API_PREFIX_V1))


@router.post(route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.REQUEST.value),
             name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.REQUEST, Action.CREATE),
             description="Queue a scan request.",
             status_code=202,
             response_model=StatusResponse)
async def post_scan_request(
        scan_request_info: ScanRequestModel,
        response: Response,
        request: Request,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        job_name: Optional[str] = Header(default=None, alias="X-Job-Name")) -> StatusResponse:
    # Perform HMAC check outside the broad try so auth failures propagate as 401
    await require_dsx_hmac_inbound(request)
    try:
        dsx_logging.debug(f"Queuing scan task {scan_request_info.location}")

        # (Optional) Idempotency: if provided, you can de-dupe here using Redis before send_task.
        # Skipping the storage logic for brevity; pattern shown for header plumb-through.

        # Ensure a scan_job_id exists (connectors should set one; generate if missing)
        if not getattr(scan_request_info, "scan_job_id", None):
            scan_request_info.scan_job_id = str(_uuid.uuid4())

        # If job paused/cancelled, reject new enqueues (best-effort)
        try:
            r = getattr(request.app.state, "redis", None)
            if r is not None:
                job_key = f"dsxconnect:job:{scan_request_info.scan_job_id}"
                flags = await r.hmget(job_key, "paused", "cancel")
                if flags and (flags[0] == "1" or flags[1] == "1"):
                    response.status_code = 409
                    return StatusResponse(status=StatusResponseEnum.ERROR,
                                          message="Job paused/cancelled",
                                          description=f"scan_job_id={scan_request_info.scan_job_id}")
        except Exception:
            pass

        result = celery_app.send_task(
            Tasks.REQUEST,
            queue=Queues.REQUEST,
            args=[scan_request_info.model_dump()],)

        # Location header: /api/v1/dsx-connect/scan-request/{task_id}
        task_id = result.id
        response.headers["Location"] = api_path(DSXConnectAPI.SCAN_PREFIX, ScanPath.REQUEST, task_id)

        # Update per-job counters in Redis (best-effort)
        try:
            r = getattr(request.app.state, "redis", None)
            if r is not None:
                job_id = scan_request_info.scan_job_id
                key = f"dsxconnect:job:{job_id}"
                now = str(int(time.time()))
                await r.hsetnx(key, "job_id", job_id)
                await r.hsetnx(key, "status", "running")
                await r.hsetnx(key, "started_at", now)
                # Optional connector info
                try:
                    conn = getattr(scan_request_info, "connector", None)
                    if conn is not None and getattr(conn, "uuid", None):
                        await r.hsetnx(key, "connector_uuid", str(conn.uuid))
                except Exception:
                    pass
                await r.hincrby(key, "enqueued_count", 1)
                try:
                    await r.rpush(f"{key}:tasks", task_id)
                except Exception:
                    pass
                mapping = {"last_update": now}
                if job_name:
                    mapping["job_name"] = job_name
                await r.hset(key, mapping=mapping)
                # Optional TTL to avoid stale jobs piling up
                await r.expire(key, 7 * 24 * 3600)
        except Exception:
            pass

        return StatusResponse(
            status=StatusResponseEnum.SUCCESS,
            description=f"Scan task queued for connector: {scan_request_info.connector_url}",
            message=f"Scan task ID: {result.id}")

    except (BrokerOperationalError, RedisConnectionError) as e:
        # Broker/Redis unreachable -> 503 Service Unavailable
        dsx_logging.exception("Broker/Redis connection error during send_task")
        response.status_code = 503
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            description="Task broker unavailable",
            message=str(e),
        )
    except (RedisTimeoutError, CeleryTimeoutError) as e:
        # Timeouts talking to broker/backend -> 504 Gateway Timeout
        dsx_logging.exception("Timeout talking to broker/backend during send_task")
        response.status_code = 504
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            description="Timed out queuing scan task",
            message=str(e),
        )
    except CeleryError as e:
        # Celery-level issues (serialization, routing, etc.) -> 502 Bad Gateway
        dsx_logging.exception("Celery error during send_task")
        response.status_code = 502
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            description="Failed to queue scan task (celery error)",
            message=str(e),
        )
    except Exception as e:
        # Unknown failure -> 500 Internal Server Error
        dsx_logging.exception("Unexpected error queuing scan task")
        response.status_code = 500
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            description="Failed to queue scan task",
            message=str(e),
        )


# Lightweight protected endpoint for HMAC verification that does not enqueue to Celery
@router.post(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, "auth_check"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.REQUEST, Action.HEALTH),
    description="Verify DSX-HMAC signing without hitting Celery.",
    status_code=200,
    response_model=StatusResponse,
)
async def post_scan_auth_check(request: Request) -> StatusResponse:
    await require_dsx_hmac_inbound(request)
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message="auth_ok", description="HMAC verified")


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.REQUEST.value, "{task_id}"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.REQUEST, Action.STATUS),
    response_model=ScanRequestStatus,
    description="Poll the status of a previously queued scan task."
)
async def get_scan_status(task_id: str = Path(...), response: Response = None) -> ScanRequestStatus:
    ar = AsyncResult(task_id, app=celery_app)

    # Map Celery state to your API status
    if ar.state in {"PENDING", "RECEIVED", "STARTED", "RETRY"}:
        # Optional: hint clients to back off a bit
        if response is not None:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Retry-After"] = "2"
        return ScanRequestStatus(task_id=task_id, state=ar.state, status=StatusResponseEnum.SUCCESS)

    if ar.state == "SUCCESS":
        # If your worker returns a value, expose it here (safe to omit if not used)
        return ScanRequestStatus(task_id=task_id, state="SUCCESS", status=StatusResponseEnum.SUCCESS, result=ar.result)

    # FAILURE (and unknowns) -> include error info if present
    err_msg = None
    try:
        err_msg = str(ar.result) if ar.result else None
    except Exception:
        pass
    return ScanRequestStatus(task_id=task_id, state="FAILURE", status=StatusResponseEnum.ERROR, error=err_msg)
