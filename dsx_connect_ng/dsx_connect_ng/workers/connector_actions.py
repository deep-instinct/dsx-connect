from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config, resolve_remediation_capabilities
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.contracts import RemediationRequested
from dsx_connect_ng.jobs.models import (
    ConnectorActionRequest,
    ConnectorItemAction,
    ConnectorRemediationResponse,
    RemediationResult,
)
from dsx_connect_ng.readers.base import TerminalScanError
from shared.auth.hmac import make_hmac_header


@dataclass(frozen=True)
class ConnectorActionRuntimeConfig:
    endpoint_url: str
    connector_url: str
    auth_mode: str = "none"
    header_name: str | None = None
    header_value: str | None = None
    hmac_key_id: str | None = None
    hmac_secret: str | None = None
    timeout_seconds: float = 30.0


def _build_auth_headers(config: ConnectorActionRuntimeConfig, *, method: str, url: str, body: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    if config.auth_mode == "static_header":
        if not config.header_name or not config.header_value:
            raise TerminalScanError(
                "connector_action_auth_config_invalid",
                "static_header auth requires header_name and header_value",
            )
        headers[config.header_name] = config.header_value
        return headers
    if config.auth_mode == "dsx_hmac":
        if not config.hmac_key_id or not config.hmac_secret:
            raise TerminalScanError(
                "connector_action_auth_config_invalid",
                "dsx_hmac auth requires hmac_key_id and hmac_secret",
            )
        parsed = urlparse(url)
        path_q = parsed.path or "/"
        if parsed.query:
            path_q += f"?{parsed.query}"
        headers["Authorization"] = make_hmac_header(config.hmac_key_id, config.hmac_secret, method.upper(), path_q, body)
    return headers


def resolve_connector_action_runtime_config(
    request: RemediationRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> ConnectorActionRuntimeConfig:
    if control_plane is None or not request.integration_id:
        raise TerminalScanError(
            "connector_action_config_missing",
            "connector remediation requires integration-level connector proxy configuration",
        )
    integration = control_plane.get_integration_or_404(request.integration_id)
    runtime_config = parse_integration_runtime_config(integration.config)
    proxy = runtime_config.reader.proxy if runtime_config.reader and runtime_config.reader.proxy else None

    endpoint_url = proxy.endpoint_url if proxy else None
    connector_url = None
    if endpoint_url:
        connector_url = endpoint_url.rsplit("/", 1)[0]
        endpoint_url = f"{connector_url}/item_action"
    else:
        base_url = proxy.base_url if proxy else None
        connector_name = proxy.connector_name if proxy else None
        if base_url and connector_name:
            connector_url = f"{str(base_url).rstrip('/')}/{str(connector_name).strip('/')}"
            endpoint_url = f"{connector_url}/item_action"
    if not endpoint_url or not connector_url:
        raise TerminalScanError(
            "connector_action_config_missing",
            "integration reader.proxy config must define endpoint_url or base_url + connector_name for remediation",
            details={"integrationId": request.integration_id},
        )

    timeout = proxy.timeout_seconds if proxy else 30.0
    try:
        timeout_seconds = float(timeout)
    except Exception:
        timeout_seconds = 30.0

    return ConnectorActionRuntimeConfig(
        endpoint_url=str(endpoint_url),
        connector_url=str(connector_url),
        auth_mode=str(proxy.auth_mode if proxy else "none"),
        header_name=proxy.header_name if proxy else None,
        header_value=proxy.header_value if proxy else None,
        hmac_key_id=proxy.hmac_key_id if proxy else None,
        hmac_secret=proxy.hmac_secret if proxy else None,
        timeout_seconds=timeout_seconds,
    )


def build_legacy_connector_action_payload(
    request: RemediationRequested,
    *,
    connector_action: ConnectorActionRequest,
    connector_url: str,
) -> dict[str, Any]:
    plan = request.remediation_plan.remediation_plan
    normalized_request = request.as_connector_remediation_request()
    location = request.content_source.locator or request.object_identity
    metainfo = request.object_identity
    payload: dict[str, Any] = {
        "location": str(location),
        "metainfo": str(metainfo),
        "connector_url": connector_url,
        "connector": {
            "url": connector_url,
            "item_action": connector_action.item_action,
            "item_action_move_metainfo": connector_action.item_action_move_metainfo or "",
        },
        "item_action": connector_action.item_action,
        "item_action_move_metainfo": connector_action.item_action_move_metainfo or "",
        "tags": connector_action.tags,
        "action_details": connector_action.details,
        "requested_action": {
            "type": normalized_request.action,
            "destination": normalized_request.destination,
            "tags": normalized_request.tags,
            "details": normalized_request.details,
        },
        "scan_context": {
            "scan_guid": request.scan_result.scan_guid,
            "verdict": request.scan_result.verdict,
        },
        "scan_job_id": request.job_id,
        "job_item_id": request.job_item_id,
    }
    size_in_bytes = plan.get("sizeInBytes") or plan.get("size_in_bytes")
    if isinstance(size_in_bytes, int):
        payload["size_in_bytes"] = size_in_bytes
    return payload


def _normalize_response_action(value: Any, *, fallback: ConnectorItemAction) -> ConnectorItemAction:
    normalized = str(value or fallback).strip().lower()
    if normalized in {"nothing", "delete", "move", "tag", "movetag"}:
        return normalized
    return fallback


def normalize_connector_remediation_response(
    payload: dict[str, Any],
    *,
    fallback_action: ConnectorItemAction,
    target_path: str | None = None,
) -> ConnectorRemediationResponse:
    status = str(payload.get("status") or "").strip().lower()
    if status in {"ok", "success", "completed"}:
        normalized_status = "success"
    elif status in {"noop", "nothing"}:
        normalized_status = "nothing"
    elif status in {"not_supported", "unsupported"}:
        normalized_status = "not_supported"
    elif status in {"permission_error", "forbidden"}:
        normalized_status = "permission_error"
    elif status in {"object_not_found", "not_found"}:
        normalized_status = "object_not_found"
    elif status in {"transient_platform_error", "retry", "temporary_error"}:
        normalized_status = "transient_platform_error"
    else:
        normalized_status = "error"

    applied_action = _normalize_response_action(
        payload.get("applied_action") or payload.get("appliedAction") or payload.get("action"),
        fallback=fallback_action,
    )
    resolved_target_path = (
        payload.get("target_path")
        or payload.get("targetPath")
        or payload.get("path")
        or target_path
    )
    error_code = payload.get("error_code") or payload.get("errorCode")
    error_message = payload.get("error_message") or payload.get("errorMessage") or payload.get("message")

    return ConnectorRemediationResponse(
        status=normalized_status,
        applied_action=applied_action,
        targetPath=str(resolved_target_path) if resolved_target_path else None,
        details=payload.get("details") or payload,
        errorCode=str(error_code) if error_code is not None else None,
        errorMessage=str(error_message) if error_message is not None else None,
    )


def _connector_item_action_sync(
    request: RemediationRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> RemediationResult:
    config = resolve_connector_action_runtime_config(request, control_plane=control_plane)
    normalized_request = request.as_connector_remediation_request()
    connector_action = request.as_connector_action_request()
    if control_plane is not None and request.integration_id:
        integration = control_plane.get_integration_or_404(request.integration_id)
        capabilities = resolve_remediation_capabilities(
            integration.config,
            default_enabled=bool(integration.capability_remediate),
        )
        if not capabilities.supports_action(normalized_request.action):
            raise TerminalScanError(
                "connector_action_not_supported",
                f"connector does not support remediation action '{normalized_request.action}'",
                details={
                    "integrationId": request.integration_id,
                    "requestedAction": normalized_request.action,
                    "capabilities": capabilities.model_dump(mode="json"),
                },
            )
    payload = build_legacy_connector_action_payload(
        request,
        connector_action=connector_action,
        connector_url=config.connector_url,
    )
    body = __import__("json").dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **_build_auth_headers(config, method="PUT", url=config.endpoint_url, body=body),
    }
    req = Request(config.endpoint_url, data=body, headers=headers, method="PUT")
    try:
        with urlopen(req, timeout=config.timeout_seconds) as response:
            raw = response.read()
            payload = __import__("json").loads(raw.decode("utf-8") or "{}")
    except HTTPError as exc:
        raw = exc.read()
        details: dict[str, Any] = {"endpointUrl": config.endpoint_url, "statusCode": exc.code}
        if raw:
            try:
                details["response"] = __import__("json").loads(raw.decode("utf-8"))
            except Exception:
                details["responseText"] = raw.decode("utf-8", errors="replace")
        if exc.code in (404, 422):
            raise TerminalScanError("connector_action_rejected", f"connector item_action failed with http {exc.code}", details=details) from exc
        raise RuntimeError(f"connector item_action transient failure: http {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"connector item_action transport failure: {exc}") from exc

    status = str(payload.get("status") or "").lower()
    if status == "error":
        raise TerminalScanError(
            "connector_action_failed",
            str(payload.get("message") or "connector item_action failed"),
            details=payload,
        )
    normalized_response = normalize_connector_remediation_response(
        payload,
        fallback_action=connector_action.item_action,
        target_path=connector_action.item_action_move_metainfo,
    )
    if normalized_response.status == "nothing":
        outcome = "noop"
    elif normalized_response.status == "success":
        outcome = "succeeded"
    else:
        outcome = "failed"
    return RemediationResult(
        action=str(request.remediation_plan.remediation_plan.get("action") or "noop"),
        outcome=outcome,
        targetPath=normalized_response.target_path,
        details={
            "worker": "connector_item_action",
            "requestedAction": normalized_request.model_dump(mode="json"),
            "connectorAction": connector_action.model_dump(mode="json"),
            "connectorResponse": normalized_response.model_dump(mode="json", by_alias=True),
        },
    )


async def execute_connector_item_action(
    request: RemediationRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> RemediationResult:
    return await asyncio.to_thread(_connector_item_action_sync, request, control_plane=control_plane)
