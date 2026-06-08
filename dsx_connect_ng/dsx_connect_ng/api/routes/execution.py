import asyncio

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from dsx_connect_ng.api.job_bus_dependencies import get_job_bus
from dsx_connect_ng.api.job_service_dependencies import get_job_service
from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.bus import JobBus
from dsx_connect_ng.jobs.topology import rabbitmq_topology_summary
from dsx_connect_ng.jobs.models import (
    BatchJobRecord,
    BatchJobSubmitRequest,
    DeliveryStageUpdateRequest,
    DeliveryRequest,
    DiannaStageUpdateRequest,
    DiannaAnalysisRequest,
    JobItemRecord,
    JobProgressSnapshot,
    JobRecord,
    JobSubmitRequest,
    OutboxFlushResult,
    OutboxRecord,
    PolicyDecision,
    PolicyStageUpdateRequest,
    RemediationStageUpdateRequest,
    RemediationRequest,
    ScanStageUpdateRequest,
)
from dsx_connect_ng.jobs.service import JobService

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/status")
async def execution_status(
    request: Request,
    bus: JobBus = Depends(get_job_bus),
) -> dict:
    bootstrap = getattr(request.app.state, "job_bus_bootstrap", None)
    service_bootstrap = getattr(request.app.state, "job_service_bootstrap", None)
    return {
        "surface": "execution",
        "service": settings.service_name,
        "stability_goal": "scan_path_reliability_boundary",
        "configured_job_bus_mode": settings.job_bus_backend,
        "job_repository_backend": getattr(service_bootstrap, "backend", "unknown"),
        "job_repository_detail": getattr(service_bootstrap, "detail", None),
        "job_bus_backend": getattr(bootstrap, "backend", "unknown"),
        "job_bus_detail": getattr(bootstrap, "detail", None),
        "job_bus_status": await bus.status(),
        "configured_topology": rabbitmq_topology_summary(settings),
        "intended_callers": [
            "connectors",
            "workers",
            "backend_services",
        ],
        "notes": [
            "Execution APIs must remain machine-oriented.",
            "UI-facing convenience payloads do not belong here.",
        ],
    }


@router.get("/topology")
async def execution_topology() -> dict:
    return {
        "surface": "execution_topology",
        "service": settings.service_name,
        "transport": settings.job_bus_backend,
        "topology": rabbitmq_topology_summary(settings),
        "notes": [
            "This endpoint exposes configured queue topology only.",
            "It does not inspect live broker queue depth or message contents.",
            "Manual DLQ replay is not implemented yet.",
        ],
    }

@router.get("/jobs", response_model=list[JobRecord])
def list_jobs(
    integration_id: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: JobService = Depends(get_job_service),
) -> list[JobRecord]:
    return service.list_jobs(integration_id=integration_id, state=state, limit=limit)


@router.post("/jobs", response_model=JobRecord)
async def submit_job(
    payload: JobSubmitRequest,
    service: JobService = Depends(get_job_service),
) -> JobRecord:
    return await run_in_threadpool(lambda: asyncio.run(service.submit_job(payload)))


@router.post("/jobs/batch", response_model=BatchJobRecord)
async def submit_batch_job(
    payload: BatchJobSubmitRequest,
    service: JobService = Depends(get_job_service),
) -> BatchJobRecord:
    return await run_in_threadpool(lambda: asyncio.run(service.submit_batch_job(payload)))


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> JobRecord:
    return service.get_job_or_404(job_id)


@router.get("/jobs/{job_id}/batch", response_model=BatchJobRecord)
def get_batch_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> BatchJobRecord:
    return service.get_batch_job_or_404(job_id)


@router.post("/jobs/{job_id}/cancel", response_model=BatchJobRecord)
def cancel_job(
    job_id: str,
    service: JobService = Depends(get_job_service),
) -> BatchJobRecord:
    return service.cancel_job(job_id)


@router.get("/jobs/{job_id}/progress", response_model=JobProgressSnapshot)
def get_job_progress(
    job_id: str,
    item_limit: int = Query(
        default=100,
        ge=1,
        le=5000,
        description="Number of item rows to sample for latency/throughput derivation; counts always use full job summary.",
    ),
    service: JobService = Depends(get_job_service),
) -> JobProgressSnapshot:
    return service.get_job_progress(job_id, item_limit=item_limit)


@router.get("/jobs/{job_id}/items", response_model=list[JobItemRecord])
def list_job_items(
    job_id: str,
    state: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    service: JobService = Depends(get_job_service),
) -> list[JobItemRecord]:
    return service.list_job_items(job_id=job_id, state=state, limit=limit)


@router.get("/job-items/{job_item_id}", response_model=JobItemRecord)
def get_job_item(
    job_item_id: str,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return service.get_job_item_or_404(job_item_id)


@router.post("/job-items/{job_item_id}/scan-stage", response_model=JobItemRecord)
async def update_scan_stage(
    job_item_id: str,
    payload: ScanStageUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.advance_scan_stage(job_item_id, payload.as_stage_update_request())


@router.post("/job-items/{job_item_id}/remediation-stage", response_model=JobItemRecord)
async def update_remediation_stage(
    job_item_id: str,
    payload: RemediationStageUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.advance_remediation_stage(job_item_id, payload.as_stage_update_request())


@router.post("/job-items/{job_item_id}/policy-stage", response_model=JobItemRecord)
async def update_policy_stage(
    job_item_id: str,
    payload: PolicyStageUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.advance_policy_stage(job_item_id, payload.as_stage_update_request())


@router.post("/job-items/{job_item_id}/delivery-stage", response_model=JobItemRecord)
def update_delivery_stage(
    job_item_id: str,
    payload: DeliveryStageUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return service.update_delivery_stage(job_item_id, payload.as_stage_update_request())


@router.post("/job-items/{job_item_id}/result-sink-request", response_model=JobItemRecord)
async def request_workflow_summary_emit(
    job_item_id: str,
    payload: DeliveryRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.request_workflow_summary_emit(job_item_id, payload)


@router.post("/job-items/{job_item_id}/delivery-request", response_model=JobItemRecord, include_in_schema=False)
async def request_result_delivery(
    job_item_id: str,
    payload: DeliveryRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.request_workflow_summary_emit(job_item_id, payload)


@router.post("/job-items/{job_item_id}/dianna-request", response_model=JobItemRecord)
async def request_dianna_analysis(
    job_item_id: str,
    payload: DiannaAnalysisRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.request_dianna_analysis(job_item_id, payload)


@router.post("/job-items/{job_item_id}/dianna-stage", response_model=JobItemRecord)
async def update_dianna_stage(
    job_item_id: str,
    payload: DiannaStageUpdateRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.advance_dianna_stage(job_item_id, payload.as_stage_update_request())


@router.post("/job-items/{job_item_id}/remediation-request", response_model=JobItemRecord)
async def request_remediation(
    job_item_id: str,
    payload: RemediationRequest,
    service: JobService = Depends(get_job_service),
) -> JobItemRecord:
    return await service.request_remediation(job_item_id, payload)


@router.get("/outbox", response_model=list[OutboxRecord])
def list_outbox(
    publish_state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: JobService = Depends(get_job_service),
) -> list[OutboxRecord]:
    return service.list_outbox(publish_state=publish_state, limit=limit)


@router.get("/outbox/{outbox_id}", response_model=OutboxRecord)
def get_outbox(
    outbox_id: str,
    service: JobService = Depends(get_job_service),
) -> OutboxRecord:
    return service.get_outbox_or_404(outbox_id)


@router.post("/outbox/flush", response_model=OutboxFlushResult)
async def flush_outbox(
    limit: int = Query(default=100, ge=1, le=500),
    service: JobService = Depends(get_job_service),
) -> OutboxFlushResult:
    return await service.flush_outbox(limit=limit)
