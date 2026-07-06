from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from dsx_connect_ng.api.dependencies import get_control_plane_service
from dsx_connect_ng.api.job_service_dependencies import get_job_service
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config, resolve_policy_runtime_config
from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceRecord,
    IntegrationCreate,
    IntegrationRecord,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeRecord,
    ProtectedScopeUpdate,
    utcnow,
)
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.models import (
    BatchJobRecord,
    BatchJobSubmitRequest,
    JobItemRecord,
    JobItemSummary,
    JobRecord,
    StageUpdateRequest,
)
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.version import DSX_CONNECT_VERSION

router = APIRouter(prefix="/ui", tags=["ui"])

_OPERATOR_CONSOLE_PATH = Path(__file__).resolve().parents[2] / "ui" / "operator_console.html"


class ConnectorHealthStatus(BaseModel):
    status: str = "unknown"
    endpoint: str | None = None
    checked_at: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class UIDsxaStatusResponse(BaseModel):
    state: str = "unknown"
    label: str = "DSXA unknown"
    mode: str = "stub"
    base_url: str | None = None
    endpoint: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class UIMetaResponse(BaseModel):
    product: str = "DSX-Connect"
    version: str
    display_name: str


class UIIntegrationSummary(BaseModel):
    integration: IntegrationRecord
    scope_count: int = 0
    scopes: list[ProtectedScopeRecord] = Field(default_factory=list)
    connector_instance_count: int = 0
    connector_instances: list[ConnectorInstanceRecord] = Field(default_factory=list)
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


class UIScanResultProgressSummary(BaseModel):
    total_items: int = 0
    terminal_items: int = 0
    percent_complete: float | None = None
    completed_items: int = 0
    failed_items: int = 0
    cancelled_items: int = 0


class UIScanResultFindingsSummary(BaseModel):
    clean: int = 0
    malicious: int = 0
    suspicious: int = 0
    unknown: int = 0
    failed: int = 0
    cancelled: int = 0
    sampled_items: int = 0
    sample_limit: int = 0


class UIScanResultRemediationSummary(BaseModel):
    pending: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    not_required: int = 0


class UIScanResultTargetSummary(BaseModel):
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str | None = None
    source: str | None = None
    label: str | None = None


class UICancelSemantics(BaseModel):
    mode: str = "cooperative"
    message: str = "Cancel stops future work quickly; files already claimed into an in-memory scan batch may finish."
    immediate_file_level_cancel: bool = False


class UIScanResultSummary(BaseModel):
    job: JobRecord
    target: UIScanResultTargetSummary
    progress: UIScanResultProgressSummary
    findings: UIScanResultFindingsSummary
    remediation: UIScanResultRemediationSummary
    started_at: str
    finished_at: str | None = None
    cancel: UICancelSemantics = Field(default_factory=UICancelSemantics)
    latest_items: list[UIJobItemStageSummary] = Field(default_factory=list)
    failure_reason: str | None = None


class UIScanResultsResponse(BaseModel):
    results: list[UIScanResultSummary] = Field(default_factory=list)


class UIOverview(BaseModel):
    integrations: list[UIIntegrationSummary] = Field(default_factory=list)
    scopes: list[ProtectedScopeRecord] = Field(default_factory=list)
    jobs: list[JobRecord] = Field(default_factory=list)
    job_summaries: list[UIJobSummary] = Field(default_factory=list)


class UIAssetsConnectorsResponse(BaseModel):
    connectors: list[UIIntegrationSummary] = Field(default_factory=list)


class UIScopeScanRequest(BaseModel):
    reader_strategy: str = "proxy"
    path: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
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


class UIProtectedAssetSummary(BaseModel):
    integration_id: str
    integration_display_name: str
    platform: str
    asset_type: str
    id: str
    display_name: str | None = None
    selector: str
    coverage_state: str = "unknown"
    matching_scope_id: str | None = None
    policy: dict[str, Any] = Field(default_factory=dict)
    last_scan: dict[str, Any] | None = None
    findings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UIAssetsProtectedResponse(BaseModel):
    assets: list[UIProtectedAssetSummary] = Field(default_factory=list)
    unsupported_integrations: list[str] = Field(default_factory=list)
    failed_integrations: list[dict[str, Any]] = Field(default_factory=list)
    next_cursors: dict[str, str | None] = Field(default_factory=dict)


class UIPolicyAssignmentSummary(BaseModel):
    integration_id: str
    integration_display_name: str
    scope_id: str
    scope_display_name: str
    selector: str
    enabled: bool
    source: str = "scope"


class UIPolicySummary(BaseModel):
    policy_id: str
    display_name: str
    status: str = "active"
    definition: dict[str, Any] = Field(default_factory=dict)
    outcome_rules: dict[str, Any] = Field(default_factory=dict)
    assigned_assets: int = 0
    assignments: list[UIPolicyAssignmentSummary] = Field(default_factory=list)
    updated_at: str | None = None


class UIPoliciesResponse(BaseModel):
    policies: list[UIPolicySummary] = Field(default_factory=list)


class UIScopePolicyUpdateRequest(BaseModel):
    policy: dict[str, Any] = Field(default_factory=dict)


class UIToggleEnabledRequest(BaseModel):
    enabled: bool


class UIDemoSeedResponse(BaseModel):
    integrations: list[IntegrationRecord] = Field(default_factory=list)
    scopes: list[ProtectedScopeRecord] = Field(default_factory=list)
    jobs: list[UIJobSummary] = Field(default_factory=list)
    message: str = "demo_seed_applied"


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


def _verdict_bucket(verdict: str | None) -> str:
    normalized = str(verdict or "").strip().lower()
    if normalized in {"benign", "clean", "allowed", "allow"}:
        return "clean"
    if normalized in {"malicious", "malware", "infected", "non-compliant", "non_compliant"}:
        return "malicious"
    if normalized in {"suspicious"}:
        return "suspicious"
    return "unknown"


def _summarize_findings(items: list[JobItemRecord], *, sample_limit: int) -> UIScanResultFindingsSummary:
    findings = UIScanResultFindingsSummary(sampled_items=len(items), sample_limit=sample_limit)
    for item in items:
        if item.state == "failed":
            findings.failed += 1
            continue
        if item.state == "cancelled":
            findings.cancelled += 1
            continue
        if item.scan_stage.state != "completed":
            findings.unknown += 1
            continue
        bucket = _verdict_bucket((item.scan_stage.result or {}).get("verdict"))
        if bucket == "clean":
            findings.clean += 1
        elif bucket == "malicious":
            findings.malicious += 1
        elif bucket == "suspicious":
            findings.suspicious += 1
        else:
            findings.unknown += 1
    return findings


def _summarize_remediation(items: list[JobItemRecord]) -> UIScanResultRemediationSummary:
    summary = UIScanResultRemediationSummary()
    for item in items:
        state = item.remediation_stage.state
        if state == "pending":
            if item.scan_stage.state in {"pending", "running"} or item.state in {"accepted", "publish_pending", "queued", "scanning"}:
                summary.not_required += 1
            else:
                summary.pending += 1
        elif state == "running":
            summary.running += 1
        elif state == "completed":
            summary.completed += 1
        elif state == "failed":
            summary.failed += 1
        elif state == "skipped":
            summary.skipped += 1
    return summary


def _scan_result_target(job: JobRecord) -> UIScanResultTargetSummary:
    payload = job.payload or {}
    label = (
        payload.get("scopeSelector")
        or payload.get("selector")
        or payload.get("path")
        or job.object_identity
        or job.scope_id
        or job.integration_id
    )
    return UIScanResultTargetSummary(
        integration_id=job.integration_id,
        scope_id=job.scope_id,
        object_identity=job.object_identity,
        source=payload.get("source"),
        label=str(label) if label is not None else None,
    )


def _summarize_scan_result(job_service: JobService, job: JobRecord, *, item_limit: int) -> UIScanResultSummary:
    progress = job_service.get_job_progress(job.job_id, item_limit=item_limit)
    items = job_service.list_job_items(job_id=job.job_id, limit=item_limit)
    failure_reason = None
    if job.error:
        failure_reason = str(job.error.get("reason") or job.error.get("code") or job.error.get("message") or "failed")
    if failure_reason is None:
        for item in items:
            failure_reason = _failure_reason_from_item(item)
            if failure_reason:
                break
    return UIScanResultSummary(
        job=job,
        target=_scan_result_target(job),
        progress=UIScanResultProgressSummary(
            total_items=progress.total_items,
            terminal_items=progress.terminal_items,
            percent_complete=progress.percent_complete,
            completed_items=progress.item_summary.completed,
            failed_items=progress.item_summary.failed,
            cancelled_items=progress.item_summary.cancelled,
        ),
        findings=_summarize_findings(items, sample_limit=item_limit),
        remediation=_summarize_remediation(items),
        started_at=job.created_at.isoformat(),
        finished_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        latest_items=[_summarize_job_item(item) for item in items[:5]],
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
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    path = f"{connector_name.strip('/')}/assets" if connector_name else "assets"
    endpoint = urllib_parse.urljoin(normalized, path)
    query = {"type": asset_type, "source": source, "limit": str(limit)}
    if cursor:
        query["cursor"] = cursor
    if asset_filter_mode and asset_filter_value:
        query["asset_filter_mode"] = asset_filter_mode
        query["asset_filter_value"] = asset_filter_value
    return f"{endpoint}?{urllib_parse.urlencode(query)}"


def _build_connector_health_url(base_url: str | None, connector_name: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    if connector_name:
        return urllib_parse.urljoin(normalized, f"{connector_name.strip('/')}/healthz")
    return urllib_parse.urljoin(normalized, "healthz")


def _build_connector_repo_check_url(base_url: str | None, connector_name: str | None, *, preview_limit: int) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    path = f"{connector_name.strip('/')}/repo_check" if connector_name else "repo_check"
    endpoint = urllib_parse.urljoin(normalized, path)
    return f"{endpoint}?{urllib_parse.urlencode({'preview': str(preview_limit)})}"


def _fetch_connector_preview(base_url: str | None, connector_name: str | None, *, limit: int) -> list[str]:
    endpoint = _build_connector_repo_check_url(base_url, connector_name, preview_limit=limit)
    if endpoint is None:
        return []
    request = urllib_request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib_request.urlopen(request, timeout=30.0) as response:
            body = response.read().decode("utf-8") or "{}"
    except urllib_error.HTTPError:
        return []
    except urllib_error.URLError:
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    preview = payload.get("preview") if isinstance(payload, dict) else None
    if not isinstance(preview, list):
        return []
    return [item.strip() for item in preview if isinstance(item, str) and item.strip()][:limit]


def _scope_relative_object_path(scope_selector: str, object_identity: str) -> str:
    selector = scope_selector.strip().strip("/")
    identity = object_identity.strip()
    if selector and identity == selector:
        return ""
    prefix = selector + "/"
    if selector and identity.startswith(prefix):
        return identity[len(prefix):]
    return identity


def _fetch_connector_assets(
    base_url: str | None,
    connector_name: str | None,
    *,
    asset_type: str,
    source: str,
    limit: int,
    cursor: str | None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> dict[str, Any]:
    endpoint = _build_connector_assets_url(
        base_url,
        connector_name,
        asset_type=asset_type,
        source=source,
        limit=limit,
        cursor=cursor,
        asset_filter_mode=asset_filter_mode,
        asset_filter_value=asset_filter_value,
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


def _effective_scanner_mode() -> str:
    mode = settings.scanner.mode
    if mode == "auto":
        return "dsxa" if settings.scanner.base_url.strip() else "stub"
    return mode


def _build_dsxa_probe_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return base_url.rstrip("/") + "/"


def _probe_dsxa_endpoint(
    *,
    endpoint: str,
    base_url: str,
    mode: str,
    headers: dict[str, str],
    timeout: float,
    verify_tls: bool,
) -> UIDsxaStatusResponse:
    request = urllib_request.Request(endpoint, method="GET", headers=headers)
    context = None
    if endpoint.startswith("https://") and not verify_tls:
        context = ssl._create_unverified_context()
    try:
        if context is not None:
            with urllib_request.urlopen(request, timeout=timeout, context=context) as response:
                return UIDsxaStatusResponse(
                    state="active",
                    label="DSXA active",
                    mode=mode,
                    base_url=base_url,
                    endpoint=endpoint,
                    details={"effective_mode": _effective_scanner_mode(), "status_code": response.status},
                )
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return UIDsxaStatusResponse(
                state="active",
                label="DSXA active",
                mode=mode,
                base_url=base_url,
                endpoint=endpoint,
                details={"effective_mode": _effective_scanner_mode(), "status_code": response.status},
            )
    except urllib_error.HTTPError as exc:
        return UIDsxaStatusResponse(
            state="active",
            label="DSXA reachable",
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            details={"effective_mode": _effective_scanner_mode(), "reason": "http_response", "status_code": exc.code},
        )
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
        return UIDsxaStatusResponse(
            state="unreachable",
            label="DSXA can't reach",
            mode=mode,
            base_url=base_url,
            endpoint=endpoint,
            details={"effective_mode": _effective_scanner_mode(), "reason": "transport_error", "message": str(exc)},
        )


def _probe_dsxa_status() -> UIDsxaStatusResponse:
    mode = _effective_scanner_mode()
    base_url = settings.scanner.base_url.strip()
    if mode == "stub":
        return UIDsxaStatusResponse(
            state="stub",
            label="DSXA stub",
            mode=settings.scanner.mode,
            base_url=base_url or None,
            details={"effective_mode": mode},
        )
    endpoint = _build_dsxa_probe_url(base_url)
    if endpoint is None:
        return UIDsxaStatusResponse(
            state="not_configured",
            label="DSXA not configured",
            mode=settings.scanner.mode,
            base_url=None,
            details={"effective_mode": mode, "reason": "scanner_base_url_not_configured"},
        )
    headers = {"Accept": "application/json"}
    if settings.scanner.auth_token:
        headers["Authorization"] = f"Bearer {settings.scanner.auth_token}"
    timeout = min(max(float(settings.scanner.timeout_seconds or 2.0), 0.1), 2.0)
    result = _probe_dsxa_endpoint(
        endpoint=endpoint,
        base_url=base_url,
        mode=settings.scanner.mode,
        headers=headers,
        timeout=timeout,
        verify_tls=settings.scanner.verify_tls,
    )
    if result.state == "unreachable" and endpoint.startswith("https://"):
        fallback_endpoint = "http://" + endpoint.removeprefix("https://")
        fallback = _probe_dsxa_endpoint(
            endpoint=fallback_endpoint,
            base_url=base_url,
            mode=settings.scanner.mode,
            headers=headers,
            timeout=min(timeout, 1.0),
            verify_tls=True,
        )
        if fallback.state == "active":
            fallback.state = "scheme_mismatch"
            fallback.label = "DSXA use HTTP"
            fallback.details["configured_endpoint"] = endpoint
            fallback.details["https_error"] = result.details.get("message")
            fallback.details["reason"] = "https_failed_http_reachable"
            return fallback
    return result


def _summarize_integration(
    integration: IntegrationRecord,
    *,
    scopes: list[ProtectedScopeRecord],
    connector_instances: list[ConnectorInstanceRecord],
) -> UIIntegrationSummary:
    runtime = parse_integration_runtime_config(integration.config)
    reader_strategy = runtime.reader.default_strategy if runtime.reader is not None else runtime.reader_strategy
    proxy = runtime.reader.proxy if runtime.reader is not None else None
    health = _connector_instance_health(connector_instances)
    if health is None:
        health = _probe_connector_health(
            proxy.base_url if proxy is not None else None,
            proxy.connector_name if proxy is not None else None,
        )
    return UIIntegrationSummary(
        integration=integration,
        scope_count=len(scopes),
        scopes=scopes,
        connector_instance_count=len(connector_instances),
        connector_instances=connector_instances,
        reader_strategy=reader_strategy,
        proxy_base_url=proxy.base_url if proxy is not None else None,
        connector_name=proxy.connector_name if proxy is not None else None,
        health=health,
    )


def _connector_instance_health(connector_instances: list[ConnectorInstanceRecord]) -> ConnectorHealthStatus | None:
    if not connector_instances:
        return None
    now = utcnow()
    live_instances = [instance for instance in connector_instances if instance.expires_at > now]
    if not live_instances:
        latest = max(connector_instances, key=lambda instance: instance.last_seen_at)
        return ConnectorHealthStatus(
            status="stale",
            endpoint=latest.base_url,
            checked_at=latest.last_seen_at.isoformat(),
            details={
                "connector_instance_id": latest.connector_instance_id,
                "last_health": latest.health,
                "expires_at": latest.expires_at.isoformat(),
            },
        )
    priority = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
    best = sorted(live_instances, key=lambda instance: priority.get(instance.health, 99))[0]
    return ConnectorHealthStatus(
        status=best.health,
        endpoint=best.base_url,
        checked_at=best.last_seen_at.isoformat(),
        details={
            "connector_instance_id": best.connector_instance_id,
            "live_instances": len(live_instances),
            "registered_instances": len(connector_instances),
        },
    )


def _connector_asset_endpoint(
    integration: IntegrationRecord,
    connector_instances: list[ConnectorInstanceRecord],
) -> tuple[str | None, str | None]:
    live_instances = [instance for instance in connector_instances if instance.expires_at > utcnow()]
    if live_instances:
        priority = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
        instance = sorted(live_instances, key=lambda item: priority.get(item.health, 99))[0]
        return instance.base_url, None
    runtime = parse_integration_runtime_config(integration.config)
    proxy = runtime.reader.proxy if runtime.reader is not None else None
    if proxy is None:
        return None, None
    return proxy.base_url, proxy.connector_name


def _list_ui_integration_summaries(service: ControlPlaneService) -> list[UIIntegrationSummary]:
    integrations = service.list_integrations()
    scopes = service.list_scopes()
    connector_instances = service.list_connector_instances()
    scopes_by_integration: dict[str, list[ProtectedScopeRecord]] = {}
    for scope in scopes:
        scopes_by_integration.setdefault(scope.integration_id, []).append(scope)
    connector_instances_by_integration: dict[str, list[ConnectorInstanceRecord]] = {}
    for connector_instance in connector_instances:
        connector_instances_by_integration.setdefault(connector_instance.integration_id, []).append(connector_instance)
    return [
        _summarize_integration(
            integration,
            scopes=scopes_by_integration.get(integration.integration_id, []),
            connector_instances=connector_instances_by_integration.get(integration.integration_id, []),
        )
        for integration in integrations
    ]


def _get_or_create_integration(service: ControlPlaneService, payload: IntegrationCreate) -> IntegrationRecord:
    for existing in service.list_integrations():
        if payload.integration_id and existing.integration_id == payload.integration_id:
            return existing
        if existing.platform == payload.platform and existing.platform_key == payload.platform_key:
            return existing
    return service.create_integration(payload)


def _get_or_create_scope(service: ControlPlaneService, payload: ProtectedScopeCreate) -> ProtectedScopeRecord:
    for existing in service.list_scopes(integration_id=payload.integration_id):
        if payload.scope_id and existing.scope_id == payload.scope_id:
            return existing
        if existing.scope_type == payload.scope_type and existing.resource_selector == payload.resource_selector:
            return existing
    return service.create_scope(payload)


def _is_demo_seed_allowed() -> bool:
    return settings.environment.strip().lower() in {"dev", "local", "test"}


async def _seed_demo_data(control_plane: ControlPlaneService, job_service: JobService) -> UIDemoSeedResponse:
    if not _is_demo_seed_allowed():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "demo_seed_disabled",
                "message": "Demo seed data is only available in dev, local, or test environments.",
            },
        )

    gcs = _get_or_create_integration(
        control_plane,
        IntegrationCreate(
            integration_id="demo-gcs",
            platform="gcs",
            platform_key="demo-gcp-project",
            display_name="Demo GCS Connector",
            capability_discover=True,
            capability_monitor=True,
            capability_enumerate=True,
            capability_read=True,
            capability_remediate=True,
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8630",
                        "connector_name": "google-cloud-storage-connector",
                        "auth_mode": "none",
                    },
                },
                "policy": {
                    "policy_id": "demo-detect-only",
                    "malicious_verdict": {"action": "detect_only"},
                },
                "remediation": {
                    "supports_move": True,
                    "supports_tag": True,
                    "supports_movetag": True,
                },
            },
        ),
    )
    fs = _get_or_create_integration(
        control_plane,
        IntegrationCreate(
            integration_id="demo-filesystem",
            platform="filesystem",
            platform_key="demo-local",
            display_name="Demo Filesystem Connector",
            capability_discover=True,
            capability_monitor=True,
            capability_enumerate=True,
            capability_read=True,
            capability_remediate=True,
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://127.0.0.1:8620",
                        "connector_name": "filesystem-connector",
                        "auth_mode": "none",
                    },
                },
                "remediation": {
                    "supports_move": True,
                    "supports_delete": True,
                },
            },
        ),
    )

    gcs_scope = _get_or_create_scope(
        control_plane,
        ProtectedScopeCreate(
            scope_id="demo-scope-gcs-finance",
            integration_id=gcs.integration_id,
            scope_type="path",
            resource_selector="demo-finance-bucket/incoming",
            display_name="Finance Incoming",
            mode="full_scan",
            post_scan_policy={
                "policy_id": "demo-quarantine-malware",
                "malicious_verdict": {"action": "quarantine", "tag_on_quarantine": True},
                "auto_dianna_on_verdicts": ["malicious"],
            },
        ),
    )
    fs_scope = _get_or_create_scope(
        control_plane,
        ProtectedScopeCreate(
            scope_id="demo-scope-fs-legal",
            integration_id=fs.integration_id,
            scope_type="path",
            resource_selector="/demo/legal-review",
            display_name="Legal Review Share",
            mode="full_scan",
            post_scan_policy={
                "policy_id": "demo-detect-only",
                "malicious_verdict": {"action": "detect_only"},
            },
        ),
    )

    gcs_batch = await job_service.submit_batch_job(
        BatchJobSubmitRequest(
            job_id="demo-job-gcs-scan",
            integration_id=gcs.integration_id,
            scope_id=gcs_scope.scope_id,
            idempotency_key="demo-seed-gcs-scan",
            payload={"source": "demo_seed", "scopeSelector": gcs_scope.resource_selector, "enumerationMode": "sample"},
            items=[
                {"object_identity": "demo-finance-bucket/incoming/vendor-invoice.pdf", "payload": {"readerStrategy": "proxy"}},
                {"object_identity": "demo-finance-bucket/incoming/payroll-export.csv", "payload": {"readerStrategy": "proxy"}},
                {"object_identity": "demo-finance-bucket/incoming/eicar-sample.txt", "payload": {"readerStrategy": "proxy"}},
            ],
        )
    )
    gcs_items = job_service.list_job_items(job_id=gcs_batch.job.job_id, limit=10)
    if gcs_items and gcs_items[0].scan_stage.state != "completed":
        job_service.complete_scan_only(
            gcs_items[0].job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "demo-clean"}),
        )
    if len(gcs_items) > 1 and gcs_items[1].scan_stage.state != "completed":
        job_service.complete_scan_only(
            gcs_items[1].job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Suspicious", "scanGuid": "demo-suspicious"}),
        )
    if len(gcs_items) > 2 and gcs_items[2].scan_stage.state != "completed":
        job_service.complete_scan_only(
            gcs_items[2].job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "demo-malicious"}),
        )
    if len(gcs_items) > 2 and gcs_items[2].remediation_stage.state != "completed":
        job_service.update_remediation_stage(
            gcs_items[2].job_item_id,
            StageUpdateRequest(
                state="completed",
                result={"action": "quarantine", "outcome": "success", "targetPath": "demo-quarantine"},
            ),
        )

    fs_batch = await job_service.submit_batch_job(
        BatchJobSubmitRequest(
            job_id="demo-job-fs-cancelled",
            integration_id=fs.integration_id,
            scope_id=fs_scope.scope_id,
            idempotency_key="demo-seed-fs-cancelled",
            payload={"source": "demo_seed", "scopeSelector": fs_scope.resource_selector, "enumerationMode": "sample"},
            items=[
                {"object_identity": "/demo/legal-review/contract-draft.docx", "payload": {"readerStrategy": "proxy"}},
                {"object_identity": "/demo/legal-review/archive.zip", "payload": {"readerStrategy": "proxy"}},
            ],
        )
    )
    if fs_batch.job.state != "cancelled":
        job_service.cancel_job(fs_batch.job.job_id)

    seeded_jobs = [
        _summarize_job(job_service, job_service.get_job_or_404(gcs_batch.job.job_id)),
        _summarize_job(job_service, job_service.get_job_or_404(fs_batch.job.job_id)),
    ]
    return UIDemoSeedResponse(
        integrations=[gcs, fs],
        scopes=[gcs_scope, fs_scope],
        jobs=seeded_jobs,
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


def _scope_policy(scopes_by_id: dict[str, ProtectedScopeRecord], scope_id: str | None) -> dict[str, Any]:
    if not scope_id:
        return {}
    scope = scopes_by_id.get(scope_id)
    return scope.post_scan_policy if scope is not None else {}


def _latest_jobs_by_scope(job_service: JobService, *, integration_ids: set[str], limit_per_integration: int = 200) -> dict[str, JobRecord]:
    latest: dict[str, JobRecord] = {}
    for integration_id in integration_ids:
        for job in job_service.list_jobs(integration_id=integration_id, limit=limit_per_integration):
            if not job.scope_id:
                continue
            existing = latest.get(job.scope_id)
            if existing is None or job.created_at > existing.created_at:
                latest[job.scope_id] = job
    return latest


def _protected_asset_last_scan(job_service: JobService, job: JobRecord | None, *, item_limit: int = 100) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if job is None:
        return None, {}
    progress = job_service.get_job_progress(job.job_id, item_limit=item_limit)
    job = job_service.get_job_or_404(job.job_id)
    items = job_service.list_job_items(job_id=job.job_id, limit=item_limit)
    findings = _summarize_findings(items, sample_limit=item_limit)
    last_scan = {
        "job_id": job.job_id,
        "state": job.state,
        "job_type": job.job_type,
        "started_at": job.created_at.isoformat(),
        "finished_at": job.completed_at.isoformat() if job.completed_at is not None else None,
        "total_items": progress.total_items,
        "terminal_items": progress.terminal_items,
        "percent_complete": progress.percent_complete,
        "completed_items": progress.item_summary.completed,
        "failed_items": progress.item_summary.failed,
        "cancelled_items": progress.item_summary.cancelled,
    }
    return last_scan, findings.model_dump(mode="json")


def _summarize_protected_assets_for_integration(
    *,
    integration: IntegrationRecord,
    asset_response: UIAssetDiscoveryResponse,
    scopes_by_id: dict[str, ProtectedScopeRecord],
    job_service: JobService,
    latest_jobs_by_scope: dict[str, JobRecord],
) -> list[UIProtectedAssetSummary]:
    assets: list[UIProtectedAssetSummary] = []
    for asset in asset_response.assets:
        last_scan, findings = _protected_asset_last_scan(
            job_service,
            latest_jobs_by_scope.get(asset.matching_scope_id or ""),
        )
        assets.append(
            UIProtectedAssetSummary(
                integration_id=integration.integration_id,
                integration_display_name=integration.display_name,
                platform=integration.platform,
                asset_type=asset_response.asset_type,
                id=asset.id,
                display_name=asset.display_name,
                selector=asset.selector,
                coverage_state=asset.coverage_state,
                matching_scope_id=asset.matching_scope_id,
                policy=_scope_policy(scopes_by_id, asset.matching_scope_id),
                last_scan=last_scan,
                findings=findings,
                metadata=asset.metadata,
            )
        )
    return assets


def _normalize_asset_filter_mode(mode: str | None) -> str | None:
    if not mode:
        return None
    normalized = mode.strip().lower().replace("_", "-")
    if normalized in {"begins-with", "starts-with", "prefix"}:
        return "begins_with"
    if normalized in {"ends-with", "suffix"}:
        return "ends_with"
    if normalized in {"contains", "substring"}:
        return "contains"
    raise HTTPException(status_code=400, detail=f"unsupported_asset_filter_mode:{mode}")


def _asset_matches_filter(asset: UIProtectedAssetSummary, *, mode: str | None, value: str | None) -> bool:
    if not mode or not value:
        return True
    needle = value.strip().lower()
    if not needle:
        return True
    haystacks = [
        asset.display_name or "",
        asset.selector,
        asset.id,
    ]
    for candidate in haystacks:
        normalized = candidate.lower()
        if mode == "begins_with" and normalized.startswith(needle):
            return True
        if mode == "ends_with" and normalized.endswith(needle):
            return True
        if mode == "contains" and needle in normalized:
            return True
    return False


def _policy_source(integration: IntegrationRecord, scope: ProtectedScopeRecord) -> str | None:
    if scope.post_scan_policy:
        return "scope"
    runtime = parse_integration_runtime_config(integration.config)
    if runtime.policy is not None:
        return "integration"
    return None


def _policy_identity(integration: IntegrationRecord, scope: ProtectedScopeRecord, definition: dict[str, Any], source: str) -> str:
    if definition.get("policy_id"):
        return str(definition["policy_id"])
    if source == "integration":
        return f"integration:{integration.integration_id}"
    return f"scope:{scope.scope_id}"


def _policy_outcome_rules(definition: dict[str, Any]) -> dict[str, Any]:
    malicious = definition.get("malicious_verdict") or {}
    return {
        "malicious_action": malicious.get("action"),
        "outcome_triggers": definition.get("outcome_triggers") or {},
        "non_compliance": definition.get("non_compliance") or {},
        "auto_dianna_on_verdicts": definition.get("auto_dianna_on_verdicts") or [],
        "non_compliant_treatment": definition.get("non_compliant_treatment"),
        "not_scanned_treatment": definition.get("not_scanned_treatment"),
        "remediation_verdicts": sorted((definition.get("remediation_plan_by_verdict") or {}).keys()),
        "result_delivery_policy": definition.get("result_delivery_policy") or {},
    }


def _list_policy_summaries(control_plane: ControlPlaneService, *, integration_id: str | None = None) -> list[UIPolicySummary]:
    integrations = control_plane.list_integrations()
    if integration_id is not None:
        integrations = [integration for integration in integrations if integration.integration_id == integration_id]
    integrations_by_id = {integration.integration_id: integration for integration in integrations}
    scopes = [
        scope
        for scope in control_plane.list_scopes()
        if scope.integration_id in integrations_by_id
    ]
    policies: dict[str, UIPolicySummary] = {}
    for scope in scopes:
        integration = integrations_by_id[scope.integration_id]
        source = _policy_source(integration, scope)
        if source is None:
            continue
        resolved = resolve_policy_runtime_config(integration.config, scope.post_scan_policy)
        definition = resolved.model_dump(mode="json", exclude_none=True)
        if not definition:
            continue
        policy_id = _policy_identity(integration, scope, definition, source)
        assignment = UIPolicyAssignmentSummary(
            integration_id=integration.integration_id,
            integration_display_name=integration.display_name,
            scope_id=scope.scope_id,
            scope_display_name=scope.display_name,
            selector=scope.resource_selector,
            enabled=scope.enabled,
            source=source,
        )
        existing = policies.get(policy_id)
        if existing is None:
            existing = UIPolicySummary(
                policy_id=policy_id,
                display_name=str(definition.get("policy_id") or scope.display_name or integration.display_name),
                status="active" if scope.enabled else "disabled",
                definition=definition,
                outcome_rules=_policy_outcome_rules(definition),
                updated_at=scope.updated_at.isoformat(),
            )
            policies[policy_id] = existing
        existing.assignments.append(assignment)
        existing.assigned_assets = len(existing.assignments)
        if assignment.enabled:
            existing.status = "active"
        if existing.updated_at is None or scope.updated_at.isoformat() > existing.updated_at:
            existing.updated_at = scope.updated_at.isoformat()
    return sorted(policies.values(), key=lambda policy: policy.display_name.lower())


@router.get("", include_in_schema=False, response_class=HTMLResponse)
async def operator_console() -> HTMLResponse:
    return HTMLResponse(_load_operator_console_html())


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
async def operator_console_slash() -> HTMLResponse:
    return HTMLResponse(_load_operator_console_html())


@router.get("/meta", response_model=UIMetaResponse)
async def get_ui_meta() -> UIMetaResponse:
    display_name = f"DSX-Connect v{DSX_CONNECT_VERSION}"
    return UIMetaResponse(version=DSX_CONNECT_VERSION, display_name=display_name)


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


@router.get("/dsxa/status", response_model=UIDsxaStatusResponse)
async def dsxa_status() -> UIDsxaStatusResponse:
    return _probe_dsxa_status()


@router.post("/demo/seed", response_model=UIDemoSeedResponse)
async def seed_ui_demo_data(
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> UIDemoSeedResponse:
    return await _seed_demo_data(control_plane, job_service)


@router.get("/integrations", response_model=list[UIIntegrationSummary])
async def list_ui_integrations(
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> list[UIIntegrationSummary]:
    return _list_ui_integration_summaries(service)


@router.get("/assets/connectors", response_model=UIAssetsConnectorsResponse)
async def list_asset_connectors(
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> UIAssetsConnectorsResponse:
    return UIAssetsConnectorsResponse(connectors=_list_ui_integration_summaries(service))


@router.post("/integrations", response_model=IntegrationRecord)
async def create_ui_integration(
    payload: IntegrationCreate,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return control_plane.create_integration(payload)


@router.patch("/integrations/{integration_id}", response_model=IntegrationRecord)
async def update_ui_integration(
    integration_id: str,
    payload: IntegrationUpdate,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return control_plane.update_integration(integration_id, payload)


@router.post("/integrations/{integration_id}/enabled", response_model=IntegrationRecord)
async def set_ui_integration_enabled(
    integration_id: str,
    payload: UIToggleEnabledRequest,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return control_plane.update_integration(integration_id, IntegrationUpdate(enabled=payload.enabled))


@router.get("/overview", response_model=UIOverview)
async def get_ui_overview(
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> UIOverview:
    summaries = _list_ui_integration_summaries(control_plane)
    scopes = control_plane.list_scopes()
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


@router.get("/scan-results", response_model=UIScanResultsResponse)
async def list_scan_results(
    integration_id: str | None = None,
    state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    item_limit: int = Query(default=100, ge=1, le=1000),
    job_service: JobService = Depends(get_job_service),
) -> UIScanResultsResponse:
    jobs = job_service.list_jobs(integration_id=integration_id, state=state, limit=limit)
    return UIScanResultsResponse(
        results=[_summarize_scan_result(job_service, job, item_limit=item_limit) for job in jobs]
    )


@router.get("/policies", response_model=UIPoliciesResponse)
async def list_policies(
    integration_id: str | None = None,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> UIPoliciesResponse:
    return UIPoliciesResponse(policies=_list_policy_summaries(control_plane, integration_id=integration_id))


@router.get("/integrations/{integration_id}/assets", response_model=UIAssetDiscoveryResponse)
async def discover_integration_assets(
    integration_id: str,
    asset_type: str = Query(default="bucket", alias="type"),
    source: str = Query(default="configured_asset"),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    asset_filter_mode: str | None = Query(default=None),
    asset_filter_value: str | None = Query(default=None),
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> UIAssetDiscoveryResponse:
    normalized_filter_mode = _normalize_asset_filter_mode(asset_filter_mode)
    integration = control_plane.get_integration_or_404(integration_id)
    base_url, connector_name = _connector_asset_endpoint(
        integration,
        control_plane.list_connector_instances(integration_id=integration_id),
    )
    asset_payload = _fetch_connector_assets(
        base_url,
        connector_name,
        asset_type=asset_type,
        source=source,
        limit=limit,
        cursor=cursor,
        asset_filter_mode=normalized_filter_mode,
        asset_filter_value=asset_filter_value,
    )
    scopes = control_plane.list_scopes(integration_id=integration_id)
    return _summarize_assets(
        integration_id=integration_id,
        asset_payload=asset_payload,
        scopes=scopes,
        requested_type=asset_type,
        requested_source=source,
    )


@router.get("/assets/protected", response_model=UIAssetsProtectedResponse)
async def list_protected_assets(
    connector_type: str | None = Query(default=None),
    integration_id: str | None = Query(default=None),
    asset_type: str = Query(default="bucket", alias="type"),
    source: str = Query(default="configured_asset"),
    coverage_state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    asset_filter_mode: str | None = Query(default=None),
    asset_filter_value: str | None = Query(default=None),
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> UIAssetsProtectedResponse:
    normalized_filter_mode = _normalize_asset_filter_mode(asset_filter_mode)
    integrations = control_plane.list_integrations()
    if integration_id is not None:
        integrations = [integration for integration in integrations if integration.integration_id == integration_id]
    if connector_type is not None:
        integrations = [integration for integration in integrations if integration.platform == connector_type]

    scopes = control_plane.list_scopes()
    scopes_by_id = {scope.scope_id: scope for scope in scopes}
    latest_jobs = _latest_jobs_by_scope(
        job_service,
        integration_ids={integration.integration_id for integration in integrations},
    )
    assets: list[UIProtectedAssetSummary] = []
    unsupported_integrations: list[str] = []
    failed_integrations: list[dict[str, Any]] = []
    next_cursors: dict[str, str | None] = {}

    for integration in integrations:
        base_url, connector_name = _connector_asset_endpoint(
            integration,
            control_plane.list_connector_instances(integration_id=integration.integration_id),
        )
        try:
            asset_payload = _fetch_connector_assets(
                base_url,
                connector_name,
                asset_type=asset_type,
                source=source,
                limit=limit,
                cursor=cursor,
                asset_filter_mode=normalized_filter_mode,
                asset_filter_value=asset_filter_value,
            )
        except HTTPException as exc:
            failed_integrations.append({"integration_id": integration.integration_id, "detail": exc.detail})
            continue

        asset_response = _summarize_assets(
            integration_id=integration.integration_id,
            asset_payload=asset_payload,
            scopes=control_plane.list_scopes(integration_id=integration.integration_id),
            requested_type=asset_type,
            requested_source=source,
        )
        next_cursors[integration.integration_id] = asset_response.next_cursor
        if asset_response.unsupported:
            unsupported_integrations.append(integration.integration_id)
        integration_assets = _summarize_protected_assets_for_integration(
            integration=integration,
            asset_response=asset_response,
            scopes_by_id=scopes_by_id,
            job_service=job_service,
            latest_jobs_by_scope=latest_jobs,
        )
        if coverage_state is not None:
            integration_assets = [asset for asset in integration_assets if asset.coverage_state == coverage_state]
        if normalized_filter_mode and asset_filter_value:
            integration_assets = [
                asset
                for asset in integration_assets
                if _asset_matches_filter(asset, mode=normalized_filter_mode, value=asset_filter_value)
            ]
        assets.extend(integration_assets)

    return UIAssetsProtectedResponse(
        assets=assets,
        unsupported_integrations=unsupported_integrations,
        failed_integrations=failed_integrations,
        next_cursors=next_cursors,
    )


@router.post("/assets/protected", response_model=ProtectedScopeRecord)
async def create_protected_asset_scope(
    payload: ProtectedScopeCreate,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return control_plane.create_scope(payload)


@router.patch("/scopes/{scope_id}", response_model=ProtectedScopeRecord)
async def update_ui_scope(
    scope_id: str,
    payload: ProtectedScopeUpdate,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return control_plane.update_scope(scope_id, payload)


@router.post("/scopes/{scope_id}/enabled", response_model=ProtectedScopeRecord)
async def set_ui_scope_enabled(
    scope_id: str,
    payload: UIToggleEnabledRequest,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return control_plane.update_scope(scope_id, ProtectedScopeUpdate(enabled=payload.enabled))


@router.put("/scopes/{scope_id}/policy", response_model=ProtectedScopeRecord)
async def update_scope_policy(
    scope_id: str,
    payload: UIScopePolicyUpdateRequest,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return control_plane.update_scope(scope_id, ProtectedScopeUpdate(post_scan_policy=payload.policy))


@router.post("/scopes/{scope_id}/scan", response_model=BatchJobRecord)
async def scan_scope_selector(
    scope_id: str,
    payload: UIScopeScanRequest | None = None,
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
) -> BatchJobRecord:
    request = payload or UIScopeScanRequest()
    scope = control_plane.get_scope_or_404(scope_id)
    integration = control_plane.get_integration_or_404(scope.integration_id)
    base_url, connector_name = _connector_asset_endpoint(
        integration,
        control_plane.list_connector_instances(integration_id=scope.integration_id),
    )
    preview_items = _fetch_connector_preview(base_url, connector_name, limit=request.limit)
    object_identities = preview_items or [request.path or scope.resource_selector]
    items = [
        {
            "object_identity": object_identity,
            "payload": {
                "readerStrategy": request.reader_strategy,
                "path": (
                    _scope_relative_object_path(scope.resource_selector, object_identity)
                    if preview_items
                    else object_identity
                ),
                **request.payload,
            },
        }
        for object_identity in object_identities
    ]
    return await job_service.submit_batch_job(
        BatchJobSubmitRequest(
            job_type="scan.batch",
            integration_id=scope.integration_id,
            scope_id=scope.scope_id,
            payload={
                "source": "ui_scope_scan",
                "scopeSelector": scope.resource_selector,
                "enumerationMode": "connector_preview" if preview_items else "selector_only",
                "itemCount": len(items),
                "enumerationLimit": request.limit,
            },
            items=items,
        )
    )
