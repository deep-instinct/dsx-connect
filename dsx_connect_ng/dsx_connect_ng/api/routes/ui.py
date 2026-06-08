from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from dsx_connect_ng.api.dependencies import get_control_plane_service
from dsx_connect_ng.api.job_service_dependencies import get_job_service
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config
from dsx_connect_ng.control_plane.models import IntegrationRecord, ProtectedScopeRecord
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.models import BatchJobRecord, BatchJobSubmitRequest, JobItemRecord, JobItemSummary, JobRecord
from dsx_connect_ng.jobs.service import JobService

router = APIRouter(prefix="/ui", tags=["ui"])

_OPERATOR_CONSOLE_PATH = Path(__file__).resolve().parents[2] / "ui" / "operator_console.html"


class ConnectorHealthStatus(BaseModel):
    status: str = "unknown"
    endpoint: str | None = None
    checked_at: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class UIIntegrationSummary(BaseModel):
    integration: IntegrationRecord
    scope_count: int = 0
    scopes: list[ProtectedScopeRecord] = Field(default_factory=list)
    reader_strategy: str | None = None
    proxy_base_url: str | None = None
    connector_name: str | None = None
    health: ConnectorHealthStatus = Field(default_factory=ConnectorHealthStatus)


class UIJobItemStageSummary(BaseModel):
    job_item_id: str
    object_identity: str
    state: str
    scan: str
    policy: str
    remediation: str
    delivery: str
    dianna: str
    failure_reason: str | None = None


class UIJobSummary(BaseModel):
    job: JobRecord
    item_summary: JobItemSummary
    latest_items: list[UIJobItemStageSummary] = Field(default_factory=list)
    failure_reason: str | None = None


class UIOverview(BaseModel):
    integrations: list[UIIntegrationSummary] = Field(default_factory=list)
    scopes: list[ProtectedScopeRecord] = Field(default_factory=list)
    jobs: list[JobRecord] = Field(default_factory=list)
    job_summaries: list[UIJobSummary] = Field(default_factory=list)


class UIScopeScanRequest(BaseModel):
    reader_strategy: str = "proxy"
    path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class UIAssetSummary(BaseModel):
    id: str
    display_name: str | None = None
    selector: str
    coverage_state: str = "unknown"
    matching_scope_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UIAssetDiscoveryResponse(BaseModel):
    integration_id: str
    asset_type: str
    source: str = "configured_asset"
    status: str = "success"
    assets: list[UIAssetSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    unsupported: bool = False
    message: str | None = None
    required_permission: str | None = None


def _failure_reason_from_item(item: JobItemRecord) -> str | None:
    error = item.error or item.scan_stage.error or item.policy_stage.error or item.remediation_stage.error or item.delivery_stage.error
    if not error:
        return None
    return str(error.get("reason") or error.get("code") or error.get("message") or "failed")


def _summarize_job_item(item: JobItemRecord) -> UIJobItemStageSummary:
    return UIJobItemStageSummary(
        job_item_id=item.job_item_id,
        object_identity=item.object_identity,
        state=item.state,
        scan=item.scan_stage.state,
        policy=item.policy_stage.state,
        remediation=item.remediation_stage.state,
        delivery=item.delivery_stage.state,
        dianna=item.dianna_stage.state,
        failure_reason=_failure_reason_from_item(item),
    )


def _summarize_job(job_service: JobService, job: JobRecord) -> UIJobSummary:
    batch = job_service.get_batch_job_or_404(job.job_id)
    items = job_service.list_job_items(job_id=job.job_id, limit=5)
    failure_reason = None
    if job.error:
        failure_reason = str(job.error.get("reason") or job.error.get("code") or job.error.get("message") or "failed")
    if failure_reason is None:
        for item in items:
            failure_reason = _failure_reason_from_item(item)
            if failure_reason:
                break
    return UIJobSummary(
        job=job,
        item_summary=batch.item_summary,
        latest_items=[_summarize_job_item(item) for item in items],
        failure_reason=failure_reason,
    )


def _load_operator_console_html() -> str:
    return _OPERATOR_CONSOLE_PATH.read_text(encoding="utf-8")


def _build_connector_assets_url(
    base_url: str | None,
    connector_name: str | None,
    *,
    asset_type: str,
    source: str,
    limit: int,
    cursor: str | None,
) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    path = f"{connector_name.strip('/')}/assets" if connector_name else "assets"
    endpoint = urllib_parse.urljoin(normalized, path)
    query = {"type": asset_type, "source": source, "limit": str(limit)}
    if cursor:
        query["cursor"] = cursor
    return f"{endpoint}?{urllib_parse.urlencode(query)}"


def _build_connector_health_url(base_url: str | None, connector_name: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    if connector_name:
        return urllib_parse.urljoin(normalized, f"{connector_name.strip('/')}/healthz")
    return urllib_parse.urljoin(normalized, "healthz")


def _fetch_connector_assets(
    base_url: str | None,
    connector_name: str | None,
    *,
    asset_type: str,
    source: str,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    endpoint = _build_connector_assets_url(
        base_url,
        connector_name,
        asset_type=asset_type,
        source=source,
        limit=limit,
        cursor=cursor,
    )
    if endpoint is None:
        return {
            "asset_type": asset_type,
            "source": source,
            "status": "unsupported",
            "assets": [],
            "unsupported": True,
            "message": "connector_endpoint_not_configured",
        }
    request = urllib_request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib_request.urlopen(request, timeout=10.0) as response:
            body = response.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib_error.HTTPError as exc:
        raw = exc.read()
        connector_detail: dict[str, Any] | str | None = None
        if raw:
            text = raw.decode("utf-8", errors="replace")
            try:
                connector_detail = json.loads(text)
            except json.JSONDecodeError:
                connector_detail = text
        if exc.code == 404:
            return {
                "asset_type": asset_type,
                "source": source,
                "status": "unsupported",
                "assets": [],
                "unsupported": True,
                "message": "asset_discovery_not_supported",
            }
        raise HTTPException(
            status_code=502,
            detail={
                "code": "connector_asset_discovery_http_error",
                "status_code": exc.code,
                "connector_detail": connector_detail,
            },
        ) from exc
    except (urllib_error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail={"code": "connector_asset_discovery_transport_error", "message": str(exc)}) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail={"code": "connector_asset_discovery_invalid_json"}) from exc


def _probe_connector_health(base_url: str | None, connector_name: str | None) -> ConnectorHealthStatus:
    endpoint = _build_connector_health_url(base_url, connector_name)
    if endpoint is None:
        return ConnectorHealthStatus(
            status="unknown",
            endpoint=None,
            details={"reason": "connector_endpoint_not_configured"},
        )
    request = urllib_request.Request(endpoint, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=2.0) as response:
            body = response.read().decode("utf-8") or "{}"
            parsed = json.loads(body)
            return ConnectorHealthStatus(
                status="healthy",
                endpoint=endpoint,
                checked_at=None,
                details=parsed if isinstance(parsed, dict) else {"raw": parsed},
            )
    except urllib_error.HTTPError as exc:
        return ConnectorHealthStatus(
            status="unhealthy",
            endpoint=endpoint,
            details={
                "reason": "http_error",
                "status_code": exc.code,
            },
        )
    except (urllib_error.URLError, TimeoutError) as exc:
        return ConnectorHealthStatus(
            status="unhealthy",
            endpoint=endpoint,
            details={
                "reason": "transport_error",
                "message": str(exc),
            },
        )
    except json.JSONDecodeError:
        return ConnectorHealthStatus(
            status="healthy",
            endpoint=endpoint,
            details={"reason": "non_json_health_response"},
        )


def _summarize_integration(
    integration: IntegrationRecord,
    *,
    scopes: list[ProtectedScopeRecord],
) -> UIIntegrationSummary:
    runtime = parse_integration_runtime_config(integration.config)
    reader_strategy = runtime.reader.default_strategy if runtime.reader is not None else runtime.reader_strategy
    proxy = runtime.reader.proxy if runtime.reader is not None else None
    health = _probe_connector_health(
        proxy.base_url if proxy is not None else None,
        proxy.connector_name if proxy is not None else None,
    )
    return UIIntegrationSummary(
        integration=integration,
        scope_count=len(scopes),
        scopes=scopes,
        reader_strategy=reader_strategy,
        proxy_base_url=proxy.base_url if proxy is not None else None,
        connector_name=proxy.connector_name if proxy is not None else None,
        health=health,
    )


def _selector_key(value: str | None) -> str:
    return str(value or "").strip().strip("/")


def _coverage_for_selector(selector: str, scopes: list[ProtectedScopeRecord]) -> tuple[str, str | None]:
    key = _selector_key(selector)
    for scope in scopes:
        candidates = {
            _selector_key(scope.resource_selector),
            _selector_key(scope.normalized_selector),
        }
        if key in candidates:
            return ("protected" if scope.enabled else "disabled"), scope.scope_id
    return "unprotected", None


def _summarize_assets(
    *,
    integration_id: str,
    asset_payload: dict[str, Any],
    scopes: list[ProtectedScopeRecord],
    requested_type: str,
    requested_source: str,
) -> UIAssetDiscoveryResponse:
    asset_type = str(asset_payload.get("asset_type") or requested_type)
    assets: list[UIAssetSummary] = []
    for raw in asset_payload.get("assets") or []:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or raw.get("id") or "").strip()
        if not selector:
            continue
        coverage_state, matching_scope_id = _coverage_for_selector(selector, scopes)
        assets.append(
            UIAssetSummary(
                id=str(raw.get("id") or selector),
                display_name=raw.get("display_name") or raw.get("displayName") or selector,
                selector=selector,
                coverage_state=coverage_state,
                matching_scope_id=matching_scope_id,
                metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            )
        )
    return UIAssetDiscoveryResponse(
        integration_id=integration_id,
        asset_type=asset_type,
        source=asset_payload.get("source") or requested_source,
        status=asset_payload.get("status") or ("unsupported" if asset_payload.get("unsupported") else "success"),
        assets=assets,
        next_cursor=asset_payload.get("next_cursor") or asset_payload.get("nextCursor"),
        unsupported=bool(asset_payload.get("unsupported", False)),
        message=asset_payload.get("message"),
        required_permission=asset_payload.get("required_permission") or asset_payload.get("requiredPermission"),
    )


@router.get("", include_in_schema=False, response_class=HTMLResponse)
async def operator_console() -> HTMLResponse:
    return HTMLResponse(_load_operator_console_html())


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def operator_console_slash() -> HTMLResponse:
    return HTMLResponse(_load_operator_console_html())


@router.get("/status")
async def ui_status() -> dict:
    return {
        "surface": "ui",
        "service": settings.service_name,
        "intended_callers": [
            "browser_frontend",
            "desktop_frontend",
            "operator_ui",
        ],
        "notes": "UI routes are presentation-oriented and must remain separate from control-plane and execution contracts.",
    }


@router.get("/integrations", response_model=list[UIIntegrationSummary])
async def list_ui_integrations(
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> list[UIIntegrationSummary]:
    integrations = service.list_integrations()
    scopes = service.list_scopes()
    scopes_by_integration: dict[str, list[ProtectedScopeRecord]] = {}
    for scope in scopes:
        scopes_by_integration.setdefault(scope.integration_id, []).append(scope)
    return [
        _summarize_integration(
            integration,
            scopes=scopes_by_integration.get(integration.integration_id, []),
        )
        for integration in integrations
    ]


@router.get("/overview", response_model=UIOverview)
async def get_ui_overview(
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> UIOverview:
    integrations = control_plane.list_integrations()
    scopes = control_plane.list_scopes()
    scopes_by_integration: dict[str, list[ProtectedScopeRecord]] = {}
    for scope in scopes:
        scopes_by_integration.setdefault(scope.integration_id, []).append(scope)
    summaries = [
        _summarize_integration(
            integration,
            scopes=scopes_by_integration.get(integration.integration_id, []),
        )
        for integration in integrations
    ]
    jobs = job_service.list_jobs(limit=50)
    job_summaries = [_summarize_job(job_service, job) for job in jobs]
    return UIOverview(integrations=summaries, scopes=scopes, jobs=jobs, job_summaries=job_summaries)


@router.get("/jobs", response_model=list[UIJobSummary])
async def list_ui_jobs(
    integration_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
    job_service: JobService = Depends(get_job_service),
) -> list[UIJobSummary]:
    jobs = job_service.list_jobs(integration_id=integration_id, state=state, limit=limit)
    return [_summarize_job(job_service, job) for job in jobs]


@router.get("/integrations/{integration_id}/assets", response_model=UIAssetDiscoveryResponse)
async def discover_integration_assets(
    integration_id: str,
    asset_type: str = Query(default="bucket", alias="type"),
    source: str = Query(default="configured_asset"),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> UIAssetDiscoveryResponse:
    integration = control_plane.get_integration_or_404(integration_id)
    runtime = parse_integration_runtime_config(integration.config)
    proxy = runtime.reader.proxy if runtime.reader is not None else None
    asset_payload = _fetch_connector_assets(
        proxy.base_url if proxy is not None else None,
        proxy.connector_name if proxy is not None else None,
        asset_type=asset_type,
        source=source,
        limit=limit,
        cursor=cursor,
    )
    scopes = control_plane.list_scopes(integration_id=integration_id)
    return _summarize_assets(
        integration_id=integration_id,
        asset_payload=asset_payload,
        scopes=scopes,
        requested_type=asset_type,
        requested_source=source,
    )


@router.post("/scopes/{scope_id}/scan", response_model=BatchJobRecord)
async def scan_scope_selector(
    scope_id: str,
    payload: UIScopeScanRequest | None = None,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> BatchJobRecord:
    request = payload or UIScopeScanRequest()
    scope = control_plane.get_scope_or_404(scope_id)
    object_identity = request.path or scope.resource_selector
    item_payload = {
        "readerStrategy": request.reader_strategy,
        "path": object_identity,
        **request.payload,
    }
    return await job_service.submit_batch_job(
        BatchJobSubmitRequest(
            job_type="scan.batch",
            integration_id=scope.integration_id,
            scope_id=scope.scope_id,
            payload={
                "source": "ui_scope_scan",
                "scopeSelector": scope.resource_selector,
                "enumerationMode": "selector_only",
            },
            items=[
                {
                    "object_identity": object_identity,
                    "payload": item_payload,
                }
            ],
        )
    )
