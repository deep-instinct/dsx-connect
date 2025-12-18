from typing import List

from fastapi import APIRouter, Request, HTTPException

from dsx_connect.models.scan_result import ScanResultModel, ScanStatsModel
from dsx_connect.config import get_config
from shared.routes import DSXConnectAPI, API_PREFIX_V1, route_name, Action, ScanPath, route_path
from dsx_connect.database.database_factory import database_scan_stats_factory, database_scan_results_factory
from redis.asyncio import Redis
from fastapi import Depends
from shared.dsx_logging import dsx_logging

router = APIRouter(prefix=route_path(API_PREFIX_V1))

config = get_config()
_results_database = database_scan_results_factory(database_loc=config.results_database.loc,
                                                  retain=config.results_database.retain)

_stats_database = database_scan_stats_factory(database_loc=config.results_database.loc)


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.RESULTS.value),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.RESULTS, Action.LIST),
    response_model=List[ScanResultModel],
    description="List recent scan results (optionally filtered by job_id)."
)
async def list_scan_results(limit: int = 200, job_id: str | None = None) -> List[ScanResultModel]:
    return _results_database.recent(limit=limit, job_id=job_id)


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.RESULTS.value, "job", "{job_id}"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.RESULTS, Action.LIST),
    response_model=List[ScanResultModel],
    description="List scan results by scan_job_id."
)
async def list_scan_results_by_job(job_id: str) -> List[ScanResultModel]:
    return _results_database.find("scan_job_id", job_id) or []

@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.RESULTS.value, "{task_id}"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.RESULTS, Action.GET),
    response_model=List[ScanResultModel],
    description="List scan results."
)
async def get_scan_result(task_id: str) -> List[ScanResultModel]:
    return _results_database.find("scan_request_task_id", task_id)


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.STATS.value),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.STATS, Action.GET),
    response_model=ScanStatsModel,
    description="Retrieve scan statistics.")
async def get_scan_stats() -> ScanStatsModel:
    return _stats_database.get()


# --- Job status (Redis) ---
@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.GET),
    description="Get job status and counters.",
)
async def get_job_status(job_id: str, request: Request) -> dict:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    data = await r.hgetall(key)
    if not data:
        raise HTTPException(status_code=404, detail="job_not_found")
    # Derive simple progress if expected_total is known
    try:
        enq = int(data.get("enqueued_count", 0))
        proc = int(data.get("processed_count", 0))
        exp = int(data.get("expected_total", -1))
        if exp > 0:
            data["progress_pct"] = f"{min(100, int(proc * 100 / exp))}"
        elif enq > 0:
            data["progress_pct"] = f"{min(100, int(proc * 100 / max(1, enq)))}"
        # Duration
        import time as _t
        started = int(data.get("started_at", 0) or 0)
        finished = int(data.get("finished_at", 0) or 0)
        now = int(_t.time())
        if started:
            data["duration_secs"] = str((finished or now) - started)
        # ETA (if total known and some progress)
        try:
            total = None
            enq_total = int(data.get("enqueued_total", -1)) if data.get("enqueued_total") is not None else -1
            if enq_total > 0:
                total = enq_total
            elif exp > 0:
                total = exp
            if total and total > 0 and started and proc > 0 and proc < total:
                elapsed = max(1, (finished or now) - started)
                throughput = proc / elapsed
                if throughput > 0:
                    remaining = max(0, total - proc)
                    eta = int(remaining / throughput)
                    data["eta_secs"] = str(eta)
                    # human friendly time remaining
                    def _fmt_eta(sec: int) -> str:
                        days, rem = divmod(sec, 86400)
                        hrs, rem = divmod(rem, 3600)
                        mins, secs = divmod(rem, 60)
                        if days > 0:
                            return f"{days}d {hrs:02d}:{mins:02d}:{secs:02d}"
                        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
                    data["time_remaining"] = _fmt_eta(eta)
        except Exception:
            pass
    except Exception:
        pass
    return data


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}", "raw"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.GET) + ":raw",
    description="Debug: return raw Redis hash for a job and TTL.",
)
async def get_job_status_raw(job_id: str, request: Request) -> dict:
    r: Redis | None = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    data = await r.hgetall(key)
    ttl = await r.ttl(key)
    return {"key": key, "ttl": ttl, "data": data}


@router.post(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}", "enqueue_done"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.UPDATE),
    description="Mark that a job has finished enqueueing items; optionally set enqueued_total.",
)
async def mark_job_enqueue_done(job_id: str, request: Request, payload: dict | None = None) -> dict:
    # Auth: require connector bearer when enabled
    try:
        from dsx_connect.app.auth_hmac_inbound import require_dsx_hmac_inbound
        await require_dsx_hmac_inbound(request)
    except Exception as e:
        # propagate FastAPI HTTPException if raised
        if isinstance(e, HTTPException):
            raise
        raise
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    now = str(int(__import__('time').time()))
    mapping = {"enqueue_done": "1", "enqueue_finished_at": now, "last_update": now}
    try:
        if isinstance(payload, dict) and isinstance(payload.get("enqueued_total"), int):
            mapping["enqueued_total"] = str(payload["enqueued_total"])
            # If expected_total isn't set, set it to enqueued_total as advisory
            await r.hsetnx(key, "expected_total", str(payload["enqueued_total"]))
    except Exception:
        pass
    await r.hset(key, mapping=mapping)
    await r.expire(key, 7 * 24 * 3600)
    try:
        dsx_logging.info(f"job.enqueue_done job={job_id} enqueued_total={mapping.get('enqueued_total','')} at={now}")
    except Exception:
        pass
    return {"ok": True}


@router.post(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}", "pause"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.UPDATE),
    description="Pause a job: prevent new tasks from being enqueued.",
)
async def pause_job(job_id: str, request: Request) -> dict:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    await r.hset(key, mapping={"paused": "1", "status": "paused", "last_update": str(int(__import__('time').time()))})
    await r.expire(key, 7 * 24 * 3600)
    # Proactively publish a job-status frame so UI reflects "paused" immediately
    try:
        notifiers = getattr(request.app.state, "notifiers", None)
        if notifiers is not None:
            data = await r.hgetall(key)
            # Normalize ints
            def _to_int(v):
                try:
                    return int(v)
                except Exception:
                    return None
            processed = _to_int(data.get("processed_count")) or 0
            enq_total = _to_int(data.get("enqueued_total"))
            expected = _to_int(data.get("expected_total"))
            enq_count = _to_int(data.get("enqueued_count")) or 0
            total = enq_total if (enq_total is not None and enq_total >= 0) else expected
            # Build summary consistent with scan_result notifications
            import time as _t
            started = _to_int(data.get("started_at")) or 0
            finished = _to_int(data.get("finished_at")) or 0
            now_ts = int(_t.time())
            duration = (finished or now_ts) - started if started else None
            # Compose event with job summary
            summary = {
                "job_id": job_id,
                "status": "paused",
                "processed_count": processed,
                "total": total,
                "enqueued_total": enq_total,
                "enqueued_count": enq_count,
                "enqueue_done": data.get("enqueue_done"),
                "last_update": data.get("last_update"),
                "duration_secs": duration,
            }
            event = {"type": "scan_result", "scan_result": {"type": "job_status"}, "job": summary}
            await notifiers.publish_scan_results(event)
    except Exception:
        # Non-fatal: SSE update is best-effort
        pass
    return {"ok": True}


@router.post(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}", "resume"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.UPDATE),
    description="Resume a paused job.",
)
async def resume_job(job_id: str, request: Request) -> dict:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    await r.hdel(key, "paused")
    await r.hset(key, mapping={"status": "running", "last_update": str(int(__import__('time').time()))})
    await r.expire(key, 7 * 24 * 3600)
    return {"ok": True}


@router.post(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value, "{job_id}", "cancel"),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.UPDATE),
    description="Cancel a job: revoke queued/started tasks and mark as cancelled.",
)
async def cancel_job(job_id: str, request: Request) -> dict:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    key = f"dsxconnect:job:{job_id}"
    # Revoke tasks (best-effort)
    try:
        from dsx_connect.taskworkers.celery_app import celery_app
        tasks = await r.lrange(f"{key}:tasks", 0, -1)
        for tid in tasks or []:
            try:
                celery_app.control.revoke(tid, terminate=False)
            except Exception:
                pass
    except Exception:
        pass
    now = str(int(__import__('time').time()))
    await r.hset(key, mapping={"status": "cancelled", "cancel": "1", "finished_at": now, "last_update": now})
    await r.expire(key, 7 * 24 * 3600)
    return {"ok": True}


@router.get(
    route_path(DSXConnectAPI.SCAN_PREFIX.value, ScanPath.JOBS.value),
    name=route_name(DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, Action.LIST),
    description="List recent jobs (summary)",
)
async def list_jobs(request: Request) -> list[dict]:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=503, detail="job_store_unavailable")
    out: list[dict] = []
    async for key in r.scan_iter(match="dsxconnect:job:*", count=100):
        try:
            data = await r.hgetall(key)
            if not data:
                continue
            # Attach job_id from key if missing
            if "job_id" not in data:
                data["job_id"] = key.rsplit(":", 1)[-1]
            # Derive simple fields
            try:
                proc = int(data.get("processed_count", 0))
                exp = int(data.get("expected_total", -1)) if data.get("expected_total") is not None else -1
                enq_total = int(data.get("enqueued_total", -1)) if data.get("enqueued_total") is not None else -1
                if enq_total > 0:
                    total = enq_total
                elif exp > 0:
                    total = exp
                else:
                    total = None
                if total:
                    data["progress_pct"] = str(min(100, int(proc * 100 / max(1, total))))
                # duration
                import time as _t
                started = int(data.get("started_at", 0) or 0)
                finished = int(data.get("finished_at", 0) or 0)
                now = int(_t.time())
                if started:
                    data["duration_secs"] = str((finished or now) - started)
                # eta
                if total and started and proc > 0 and (not finished) and proc < total:
                    elapsed = max(1, (now - started))
                    throughput = proc / elapsed
                    if throughput > 0:
                        remaining = max(0, total - proc)
                        eta = int(remaining / throughput)
                        data["eta_secs"] = str(eta)
                        # human-friendly
                        days, rem = divmod(eta, 86400)
                        hrs, rem = divmod(rem, 3600)
                        mins, secs = divmod(rem, 60)
                        data["time_remaining"] = (f"{days}d {hrs:02d}:{mins:02d}:{secs:02d}" if days > 0
                                                   else f"{hrs:02d}:{mins:02d}:{secs:02d}")
            except Exception:
                pass
            out.append(data)
        except Exception:
            continue
    return out
