from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from shared.routes import API_PREFIX_V1, route_path
from shared.models.job_models import DomainJobType, DomainJobState, JobEnvelope
from shared.dsx_logging import dsx_logging


router = APIRouter(prefix=route_path(API_PREFIX_V1))

JobType = DomainJobType
JobState = DomainJobState


class _Job(BaseModel):
    job_id: str
    job_type: JobType
    state: JobState = DomainJobState.QUEUED
    created_at: str
    updated_at: str
    integration_id: str
    scope_id: str | None = None
    parent_job_id: str | None = None
    payload: dict = Field(default_factory=dict)


class StartFullScanRequest(BaseModel):
    integration_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    requested_by: str = "manual"


class MonitorEventRequest(BaseModel):
    integration_id: str = Field(min_length=1)
    scope_id: str | None = None
    resource_identity: str = Field(min_length=1)
    should_scan: bool = True
    reason: str = "monitoring"


class EnumeratePageRequest(BaseModel):
    full_scan_job_id: str = Field(min_length=1)
    discovered_object_ids: list[str] = Field(default_factory=list)
    continuation_token: str | None = None


class FinalizeScanRequest(BaseModel):
    scan_object_job_id: str = Field(min_length=1)
    verdict: str = Field(min_length=1)
    remediation_required: bool = False
    notifications_required: bool = False


@dataclass
class _JobPreviewStore:
    jobs: dict[str, _Job] = field(default_factory=dict)
    active_full_scan_by_scope: dict[str, str] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _preview_enabled(request: Request) -> None:
    cfg = getattr(request.app.state, "config", None)
    enabled = bool(getattr(getattr(cfg, "features", None), "enable_job_model_preview", False))
    if not enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_model_preview_disabled")


def _store(request: Request) -> _JobPreviewStore:
    st = getattr(request.app.state, "job_model_preview_store", None)
    if st is None:
        st = _JobPreviewStore()
        request.app.state.job_model_preview_store = st
    return st


def _pg_repo(request: Request):
    return getattr(request.app.state, "control_plane_repo", None)


async def _mirror_preview_job(request: Request, job: _Job, full_scan_external_key: str | None = None) -> None:
    repo = _pg_repo(request)
    if repo is None:
        return
    try:
        await asyncio.to_thread(
            repo.upsert_job_preview,
            job.model_dump(),
            full_scan_external_key=full_scan_external_key,
        )
    except Exception as e:
        dsx_logging.warning(f"Job preview PostgreSQL mirror failed: {e}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job(job_type: JobType, integration_id: str, scope_id: str | None = None, parent_job_id: str | None = None, payload: dict | None = None) -> _Job:
    ts = _now()
    return _Job(
        job_id=str(uuid4()),
        job_type=job_type,
        state=DomainJobState.QUEUED,
        created_at=ts,
        updated_at=ts,
        integration_id=integration_id,
        scope_id=scope_id,
        parent_job_id=parent_job_id,
        payload=payload or {},
    )


@router.get(route_path("job-model", "preview", "envelope", "sample"))
async def sample_job_envelope(request: Request):
    _preview_enabled(request)
    now = _now()
    env = JobEnvelope(
        job_id=str(uuid4()),
        job_type=DomainJobType.SCAN_OBJECT,
        state=DomainJobState.QUEUED,
        integration_id="preview-integration",
        scope_id="preview-scope",
        object_identity="/preview/object-1",
        parent_job_id=None,
        root_job_id=None,
        correlation_id=str(uuid4()),
        source_type="manual",
        source_entity_id="ui-preview",
        idempotency_key=f"scan-object:preview-scope:/preview/object-1:{now}",
        attempt=0,
        max_attempts=5,
        created_at=now,
        updated_at=now,
        scheduled_at=now,
        payload={"example": True},
    )
    return env.model_dump()


@router.get(route_path("job-model", "preview"))
async def job_model_preview_status(request: Request):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        return {
            "enabled": True,
            "mode": "preview_only",
            "job_count": len(st.jobs),
            "active_full_scans": len(st.active_full_scan_by_scope),
            "postgres_mirror_attached": _pg_repo(request) is not None,
            "note": "In-memory domain job graph preview; does not change production queues/workers.",
        }


@router.get(route_path("job-model", "preview", "mirror-health"))
async def job_model_preview_mirror_health(request: Request):
    _preview_enabled(request)
    repo = _pg_repo(request)
    if repo is None:
        return {"enabled": True, "postgres_mirror_attached": False, "healthy": False, "detail": "mirror_not_attached"}
    try:
        await asyncio.to_thread(repo.healthcheck)
        return {"enabled": True, "postgres_mirror_attached": True, "healthy": True}
    except Exception as e:
        dsx_logging.warning(f"Job preview PostgreSQL mirror healthcheck failed: {e}")
        return {
            "enabled": True,
            "postgres_mirror_attached": True,
            "healthy": False,
            "detail": f"{type(e).__name__}: {e}",
        }


@router.get(route_path("job-model", "preview", "jobs"))
async def list_preview_jobs(request: Request, limit: int = 200, source: str = "memory"):
    _preview_enabled(request)
    src = str(source or "memory").strip().lower()
    if src not in {"memory", "postgres"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_source")

    if src == "postgres":
        repo = _pg_repo(request)
        if repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="postgres_mirror_not_attached")
        try:
            items = await asyncio.to_thread(repo.list_job_preview, limit)
            return {"source": "postgres", "items": items, "count": len(items)}
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"postgres_list_failed: {e}")

    st = _store(request)
    async with st.lock:
        items = sorted((j.model_dump() for j in st.jobs.values()), key=lambda x: x["created_at"])
    sliced = items[-max(1, min(limit, 2000)):]
    return {"source": "memory", "items": sliced, "count": len(items)}


@router.post(route_path("job-model", "preview", "full-scan", "start"), status_code=status.HTTP_201_CREATED)
async def start_full_scan_preview(request: Request, body: StartFullScanRequest):
    _preview_enabled(request)
    st = _store(request)
    scope_key = f"{body.integration_id}:{body.scope_id}"
    async with st.lock:
        active = st.active_full_scan_by_scope.get(scope_key)
        if active:
            j = st.jobs.get(active)
            if j and j.state in {DomainJobState.QUEUED, DomainJobState.RUNNING}:
                return {
                    "status": "already_active",
                    "active_job_id": active,
                    "active_job_state": j.state,
                }
        job = _new_job(
            DomainJobType.FULL_SCAN_SCOPE,
            integration_id=body.integration_id,
            scope_id=body.scope_id,
            payload={"requested_by": body.requested_by},
        )
        st.jobs[job.job_id] = job
        st.active_full_scan_by_scope[scope_key] = job.job_id

    repo = _pg_repo(request)
    if repo is not None:
        try:
            await asyncio.to_thread(
                repo.upsert_full_scan_job_preview,
                integration_external_id=body.integration_id,
                external_scope_key=body.scope_id,
                external_full_scan_key=job.job_id,
                requested_by=body.requested_by,
                status="running",
            )
        except Exception as e:
            dsx_logging.warning(f"Job preview PostgreSQL mirror failed (full-scan): {e}")
    await _mirror_preview_job(request, job, full_scan_external_key=job.job_id)
    return {"status": "created", "job": job.model_dump()}


@router.post(route_path("job-model", "preview", "full-scan", "enumerate"), status_code=status.HTTP_201_CREATED)
async def enumerate_full_scan_page_preview(request: Request, body: EnumeratePageRequest):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        parent = st.jobs.get(body.full_scan_job_id)
        if parent is None or parent.job_type != DomainJobType.FULL_SCAN_SCOPE:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="full_scan_job_not_found")

        enum_job = _new_job(
            DomainJobType.ENUMERATE_SCOPE_PAGE,
            integration_id=parent.integration_id,
            scope_id=parent.scope_id,
            parent_job_id=parent.job_id,
            payload={"continuation_token": body.continuation_token},
        )
        st.jobs[enum_job.job_id] = enum_job

        created_scan_jobs: list[dict] = []
        for object_id in body.discovered_object_ids:
            sj = _new_job(
                DomainJobType.SCAN_OBJECT,
                integration_id=parent.integration_id,
                scope_id=parent.scope_id,
                parent_job_id=parent.job_id,
                payload={"object_identity": object_id, "source_reason": "full_scan"},
            )
            st.jobs[sj.job_id] = sj
            created_scan_jobs.append(sj.model_dump())

    await _mirror_preview_job(request, enum_job, full_scan_external_key=parent.job_id)
    for sj in created_scan_jobs:
        try:
            await _mirror_preview_job(request, _Job.model_validate(sj), full_scan_external_key=parent.job_id)
        except Exception:
            pass

    return {"status": "created", "enumerate_job": enum_job.model_dump(), "scan_jobs": created_scan_jobs}


@router.post(route_path("job-model", "preview", "monitor", "ingest"), status_code=status.HTTP_201_CREATED)
async def ingest_monitor_event_preview(request: Request, body: MonitorEventRequest):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        ingest = _new_job(
            DomainJobType.MONITOR_EVENT_INGEST,
            integration_id=body.integration_id,
            scope_id=body.scope_id,
            payload={"resource_identity": body.resource_identity, "reason": body.reason, "should_scan": body.should_scan},
        )
        st.jobs[ingest.job_id] = ingest
        scan_job = None
        if body.should_scan:
            scan_job = _new_job(
                DomainJobType.SCAN_OBJECT,
                integration_id=body.integration_id,
                scope_id=body.scope_id,
                parent_job_id=ingest.job_id,
                payload={"object_identity": body.resource_identity, "source_reason": "monitoring"},
            )
            st.jobs[scan_job.job_id] = scan_job
    await _mirror_preview_job(request, ingest)
    if scan_job is not None:
        await _mirror_preview_job(request, scan_job)
    return {
        "status": "created",
        "ingest_job": ingest.model_dump(),
        "scan_job": scan_job.model_dump() if scan_job else None,
    }


@router.post(route_path("job-model", "preview", "scan", "finalize"), status_code=status.HTTP_201_CREATED)
async def finalize_scan_preview(request: Request, body: FinalizeScanRequest):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        scan_job = st.jobs.get(body.scan_object_job_id)
        if scan_job is None or scan_job.job_type != DomainJobType.SCAN_OBJECT:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan_object_job_not_found")

        finalize = _new_job(
            DomainJobType.FINALIZE_SCAN_OBJECT,
            integration_id=scan_job.integration_id,
            scope_id=scan_job.scope_id,
            parent_job_id=scan_job.job_id,
            payload={"verdict": body.verdict},
        )
        st.jobs[finalize.job_id] = finalize

        remediation = None
        notify = None
        if body.remediation_required:
            remediation = _new_job(
                DomainJobType.APPLY_REMEDIATION,
                integration_id=scan_job.integration_id,
                scope_id=scan_job.scope_id,
                parent_job_id=finalize.job_id,
                payload={"verdict": body.verdict},
            )
            st.jobs[remediation.job_id] = remediation
        if body.notifications_required:
            notify = _new_job(
                DomainJobType.SEND_NOTIFICATION,
                integration_id=scan_job.integration_id,
                scope_id=scan_job.scope_id,
                parent_job_id=finalize.job_id,
                payload={"verdict": body.verdict},
            )
            st.jobs[notify.job_id] = notify
    await _mirror_preview_job(request, finalize)
    if remediation is not None:
        await _mirror_preview_job(request, remediation)
    if notify is not None:
        await _mirror_preview_job(request, notify)

    return {
        "status": "created",
        "finalize_job": finalize.model_dump(),
        "remediation_job": remediation.model_dump() if remediation else None,
        "notification_job": notify.model_dump() if notify else None,
    }


@router.post(route_path("job-model", "preview", "jobs", "{job_id}", "state"))
async def update_preview_job_state(request: Request, job_id: str, state: JobState):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        job = st.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
        job.state = state
        job.updated_at = _now()

        if job.job_type == DomainJobType.FULL_SCAN_SCOPE and state in {DomainJobState.COMPLETED, DomainJobState.FAILED, DomainJobState.CANCELED}:
            scope_key = f"{job.integration_id}:{job.scope_id}"
            if st.active_full_scan_by_scope.get(scope_key) == job.job_id:
                del st.active_full_scan_by_scope[scope_key]

    await _mirror_preview_job(request, job, full_scan_external_key=job.job_id if job.job_type == DomainJobType.FULL_SCAN_SCOPE else None)

    return {"status": "updated", "job": job.model_dump()}
