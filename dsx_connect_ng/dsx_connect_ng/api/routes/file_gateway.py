from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from dsx_connect_ng.api.dependencies import get_control_plane_service
from dsx_connect_ng.api.job_service_dependencies import get_job_service
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.models import GatewayApplicationRecord
from dsx_connect_ng.control_plane.models import IntegrationRecord, ProtectedScopeRecord
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.models import BatchJobRecord, BatchJobSubmitRequest, ContentSource
from dsx_connect_ng.jobs.service import JobService

router = APIRouter(prefix="/files", tags=["file-gateway"])


class GatewayDestination(BaseModel):
    id: str
    integration_id: str
    scope_id: str
    display_name: str
    connector_name: str | None = None
    platform: str
    platform_key: str
    selector: str
    capabilities: list[str] = Field(default_factory=list)
    classification: str | None = None
    max_file_size_bytes: int
    policy: dict[str, Any] = Field(default_factory=dict)


class GatewayDestinationsResponse(BaseModel):
    destinations: list[GatewayDestination] = Field(default_factory=list)


class GatewayTransferResponse(BaseModel):
    transfer_id: str
    job_id: str
    state: str
    destination_id: str
    submitted_files: int
    status_url: str
    job: BatchJobRecord


class GatewayGrant(BaseModel):
    destination_ids: list[str] = Field(default_factory=list)
    scope_ids: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=lambda: ["discover", "submit", "status"])
    path_prefixes: list[str] = Field(default_factory=list)


class GatewayPrincipal(BaseModel):
    principal_id: str
    auth_method: str = "static"
    tenant_id: str | None = None
    tenant_name: str | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    business_unit: str | None = None
    application_id: str | None = None
    application_name: str | None = None
    submitted_by: str | None = None
    cost_center: str | None = None
    billing_code: str | None = None
    dsxa_protected_entity_id: int | None = None
    grants: list[GatewayGrant] = Field(default_factory=list)


def _destination_capabilities(integration: IntegrationRecord) -> list[str]:
    capabilities = ["scan"]
    configured_capabilities = integration.config.get("capabilities") if isinstance(integration.config, dict) else {}
    if integration.capability_read:
        capabilities.append("read")
    if isinstance(configured_capabilities, dict) and configured_capabilities.get("write") is True:
        capabilities.append("write")
    if integration.capability_remediate:
        capabilities.append("remediate")
    return capabilities


def _destination_id(scope: ProtectedScopeRecord) -> str:
    return scope.scope_id


def _destination_from_scope(integration: IntegrationRecord, scope: ProtectedScopeRecord) -> GatewayDestination:
    policy = scope.post_scan_policy or {}
    gateway_policy = policy.get("gateway") if isinstance(policy.get("gateway"), dict) else {}
    classification = gateway_policy.get("classification") or policy.get("classification")
    return GatewayDestination(
        id=_destination_id(scope),
        integration_id=integration.integration_id,
        scope_id=scope.scope_id,
        display_name=scope.display_name or integration.display_name,
        connector_name=None,
        platform=integration.platform,
        platform_key=integration.platform_key,
        selector=scope.resource_selector,
        capabilities=_destination_capabilities(integration),
        classification=str(classification) if classification else None,
        max_file_size_bytes=settings.gateway.max_upload_bytes,
        policy=policy,
    )


def _list_destinations(control_plane: ControlPlaneService) -> list[GatewayDestination]:
    integrations_by_id = {row.integration_id: row for row in control_plane.list_integrations()}
    destinations: list[GatewayDestination] = []
    for scope in control_plane.list_scopes():
        if not scope.enabled:
            continue
        integration = integrations_by_id.get(scope.integration_id)
        if integration is None:
            continue
        destinations.append(_destination_from_scope(integration, scope))
    return destinations


def _get_destination_or_404(
    control_plane: ControlPlaneService,
    destination_id: str,
    principal: GatewayPrincipal,
) -> GatewayDestination:
    for destination in _list_destinations(control_plane):
        if destination.id == destination_id or destination.scope_id == destination_id:
            if not _principal_can(principal, destination, "submit"):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="destination_not_allowed")
            return destination
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="destination_not_found")


def _default_anonymous_principal() -> GatewayPrincipal:
    return GatewayPrincipal(
        principal_id="anonymous",
        auth_method="none",
        submitted_by="anonymous",
        grants=[GatewayGrant()],
    )


def _principal_from_json(value: dict[str, Any], *, default_auth_method: str) -> GatewayPrincipal:
    normalized = dict(value)
    if "id" in normalized and "principal_id" not in normalized:
        normalized["principal_id"] = normalized.pop("id")
    if "principalId" in normalized and "principal_id" not in normalized:
        normalized["principal_id"] = normalized.pop("principalId")
    if "applicationId" in normalized and "application_id" not in normalized:
        normalized["application_id"] = normalized.pop("applicationId")
    if "applicationName" in normalized and "application_name" not in normalized:
        normalized["application_name"] = normalized.pop("applicationName")
    if "tenantId" in normalized and "tenant_id" not in normalized:
        normalized["tenant_id"] = normalized.pop("tenantId")
    if "tenantName" in normalized and "tenant_name" not in normalized:
        normalized["tenant_name"] = normalized.pop("tenantName")
    if "customerId" in normalized and "customer_id" not in normalized:
        normalized["customer_id"] = normalized.pop("customerId")
    if "customerName" in normalized and "customer_name" not in normalized:
        normalized["customer_name"] = normalized.pop("customerName")
    if "businessUnit" in normalized and "business_unit" not in normalized:
        normalized["business_unit"] = normalized.pop("businessUnit")
    if "submittedBy" in normalized and "submitted_by" not in normalized:
        normalized["submitted_by"] = normalized.pop("submittedBy")
    if "costCenter" in normalized and "cost_center" not in normalized:
        normalized["cost_center"] = normalized.pop("costCenter")
    if "billingCode" in normalized and "billing_code" not in normalized:
        normalized["billing_code"] = normalized.pop("billingCode")
    if "dsxaProtectedEntityId" in normalized and "dsxa_protected_entity_id" not in normalized:
        normalized["dsxa_protected_entity_id"] = normalized.pop("dsxaProtectedEntityId")
    normalized.setdefault("auth_method", default_auth_method)
    return GatewayPrincipal.model_validate(normalized)


def _static_client_records() -> list[dict[str, Any]]:
    raw = settings.gateway.static_clients_json.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="gateway_static_clients_invalid_json") from exc
    if isinstance(parsed, dict):
        if isinstance(parsed.get("clients"), list):
            return [row for row in parsed["clients"] if isinstance(row, dict)]
        return [parsed]
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="gateway_static_clients_must_be_object_or_array")


def _anonymous_principal() -> GatewayPrincipal:
    raw = settings.gateway.anonymous_principal_json.strip()
    if not raw:
        return _default_anonymous_principal()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="gateway_anonymous_principal_invalid_json") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="gateway_anonymous_principal_must_be_object")
    return _principal_from_json(parsed, default_auth_method="none")


def _principal_from_application(application: GatewayApplicationRecord) -> GatewayPrincipal:
    return GatewayPrincipal(
        principal_id=application.application_id,
        auth_method="static_bearer",
        tenant_id=application.tenant_id,
        tenant_name=application.tenant_name,
        customer_id=application.customer_id,
        customer_name=application.customer_name,
        business_unit=application.business_unit,
        application_id=application.application_id,
        application_name=application.display_name,
        submitted_by=application.submitted_by or application.application_id,
        cost_center=application.cost_center,
        billing_code=application.billing_code,
        dsxa_protected_entity_id=application.default_protected_entity_id,
        grants=[GatewayGrant.model_validate(grant.model_dump()) for grant in application.grants],
    )


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer_token_required")
    return value.strip()


def resolve_gateway_principal(
    authorization: str | None = Header(default=None),
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
) -> GatewayPrincipal:
    token = _bearer_token(authorization)
    if token:
        application = control_plane.find_gateway_application_by_static_token(token)
        if application is not None:
            return _principal_from_application(application)
        for record in _static_client_records():
            if str(record.get("token") or "") == token:
                principal_payload = dict(record)
                principal_payload.pop("token", None)
                return _principal_from_json(principal_payload, default_auth_method="static_bearer")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_gateway_token")
    if settings.gateway.allow_anonymous:
        return _anonymous_principal()
    if settings.gateway.auth_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="gateway_token_required")
    return _default_anonymous_principal()


def _grant_matches_destination(grant: GatewayGrant, destination: GatewayDestination) -> bool:
    return (
        not grant.destination_ids
        and not grant.scope_ids
        or destination.id in grant.destination_ids
        or destination.scope_id in grant.destination_ids
        or destination.scope_id in grant.scope_ids
    )


def _principal_can(principal: GatewayPrincipal, destination: GatewayDestination, action: str) -> bool:
    grants = principal.grants or [GatewayGrant()]
    for grant in grants:
        if action in grant.actions and _grant_matches_destination(grant, destination):
            return True
    return False


def _is_path_allowed(principal: GatewayPrincipal, destination: GatewayDestination, destination_path: str) -> bool:
    grants = principal.grants or [GatewayGrant()]
    normalized = destination_path.strip("/")
    for grant in grants:
        if "submit" not in grant.actions or not _grant_matches_destination(grant, destination):
            continue
        if not grant.path_prefixes:
            return True
        for prefix in grant.path_prefixes:
            cleaned = prefix.strip("/")
            if not cleaned or normalized == cleaned or normalized.startswith(f"{cleaned}/"):
                return True
    return False


def _safe_name(value: str) -> str:
    basename = Path(value or "upload.bin").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return cleaned or "upload.bin"


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata_must_be_json") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata_must_be_object")
    return value


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _policy_scanner_protected_entity(policy: dict[str, Any]) -> int | None:
    scanner = policy.get("scanner") if isinstance(policy.get("scanner"), dict) else {}
    return _first_int(scanner.get("protected_entity"), scanner.get("protectedEntity"))


def _build_gateway_attribution(
    *,
    metadata: dict[str, Any],
    destination: GatewayDestination,
    transfer_id: str,
    principal: GatewayPrincipal,
) -> dict[str, Any]:
    submitted = metadata.get("attribution") if isinstance(metadata.get("attribution"), dict) else metadata
    protected_entity = _first_int(
        principal.dsxa_protected_entity_id,
        submitted.get("protected_entity"),
        submitted.get("protectedEntity"),
        submitted.get("protected_entity_id"),
        submitted.get("protectedEntityId"),
        submitted.get("dsxa_protected_entity_id"),
        submitted.get("dsxaProtectedEntityId"),
        _policy_scanner_protected_entity(destination.policy),
    )
    attribution = {
        "source": "file_gateway_api",
        "transfer_id": transfer_id,
        "principal_id": principal.principal_id,
        "auth_method": principal.auth_method,
        "tenant_id": _first_text(principal.tenant_id, submitted.get("tenant_id"), submitted.get("tenantId")),
        "tenant_name": _first_text(principal.tenant_name, submitted.get("tenant_name"), submitted.get("tenantName")),
        "customer_id": _first_text(principal.customer_id, submitted.get("customer_id"), submitted.get("customerId")),
        "customer_name": _first_text(principal.customer_name, submitted.get("customer_name"), submitted.get("customerName"), submitted.get("customer")),
        "business_unit": _first_text(principal.business_unit, submitted.get("business_unit"), submitted.get("businessUnit")),
        "application_id": _first_text(
            principal.application_id,
            submitted.get("application_id"),
            submitted.get("applicationId"),
            submitted.get("application"),
        ),
        "application_name": _first_text(
            principal.application_name,
            submitted.get("application_name"),
            submitted.get("applicationName"),
            submitted.get("application"),
        ),
        "submitted_by": _first_text(
            principal.submitted_by,
            submitted.get("submitted_by"),
            submitted.get("submittedBy"),
            submitted.get("user"),
            submitted.get("user_id"),
            submitted.get("service_account"),
            submitted.get("serviceAccount"),
        ),
        "cost_center": _first_text(principal.cost_center, submitted.get("cost_center"), submitted.get("costCenter")),
        "billing_code": _first_text(
            principal.billing_code,
            submitted.get("billing_code"),
            submitted.get("billingCode"),
            submitted.get("chargeback_code"),
        ),
        "destination_id": destination.id,
        "destination_name": destination.display_name,
        "destination_platform": destination.platform,
        "destination_platform_key": destination.platform_key,
        "integration_id": destination.integration_id,
        "scope_id": destination.scope_id,
        "protected_target": destination.selector,
        "classification": destination.classification,
    }
    if protected_entity is not None:
        attribution["dsxa_protected_entity_id"] = protected_entity
    return {key: value for key, value in attribution.items() if value not in (None, "")}


def _item_attribution(
    base: dict[str, Any],
    *,
    file_index: int,
    file_name: str,
    size_bytes: int,
    sha256: str,
    object_identity: str,
) -> dict[str, Any]:
    return {
        **base,
        "file_index": file_index,
        "file_name": file_name,
        "file_size_bytes": size_bytes,
        "file_sha256": sha256,
        "object_identity": object_identity,
    }


async def _persist_upload(upload: UploadFile, *, transfer_dir: Path) -> tuple[Path, int, str]:
    filename = _safe_name(upload.filename or "upload.bin")
    target = transfer_dir / f"{uuid.uuid4().hex}-{filename}"
    digest = hashlib.sha256()
    total = 0
    max_bytes = settings.gateway.max_upload_bytes
    transfer_dir.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="upload_too_large")
            digest.update(chunk)
            handle.write(chunk)
    return target, total, digest.hexdigest()


@router.get("/destinations", response_model=GatewayDestinationsResponse)
def list_file_destinations(
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    principal: GatewayPrincipal = Depends(resolve_gateway_principal),
) -> GatewayDestinationsResponse:
    return GatewayDestinationsResponse(
        destinations=[
            destination
            for destination in _list_destinations(control_plane)
            if _principal_can(principal, destination, "discover")
        ]
    )


@router.post("/transfers", response_model=GatewayTransferResponse)
async def submit_file_transfer(
    destination_id: str = Form(...),
    destination_path: str = Form(default=""),
    metadata: str | None = Form(default=None),
    files: list[UploadFile] = File(...),
    control_plane: ControlPlaneService = Depends(get_control_plane_service),
    job_service: JobService = Depends(get_job_service),
    principal: GatewayPrincipal = Depends(resolve_gateway_principal),
) -> GatewayTransferResponse:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="files_required")
    destination = _get_destination_or_404(control_plane, destination_id, principal)
    if not _is_path_allowed(principal, destination, destination_path):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="destination_path_not_allowed")
    parsed_metadata = _parse_metadata(metadata)
    transfer_id = f"transfer_{uuid.uuid4().hex}"
    attribution = _build_gateway_attribution(
        metadata=parsed_metadata,
        destination=destination,
        transfer_id=transfer_id,
        principal=principal,
    )
    transfer_dir = Path(settings.gateway.upload_cache_dir).expanduser() / transfer_id
    items = []
    for index, upload in enumerate(files):
        cached_path, size_bytes, sha256 = await _persist_upload(upload, transfer_dir=transfer_dir)
        original_name = upload.filename or cached_path.name
        object_identity = str(Path(destination.selector) / destination_path.strip("/") / _safe_name(original_name))
        item_attribution = _item_attribution(
            attribution,
            file_index=index,
            file_name=original_name,
            size_bytes=size_bytes,
            sha256=sha256,
            object_identity=object_identity,
        )
        protected_entity = item_attribution.get("dsxa_protected_entity_id")
        items.append(
            {
                "object_identity": object_identity,
                "payload": {
                    "readerStrategy": "cached",
                    "source": "desktop_upload",
                    "attribution": item_attribution,
                    "transferId": transfer_id,
                    "destinationId": destination.id,
                    "destinationPath": destination_path,
                    "originalFilename": original_name,
                    "sizeInBytes": size_bytes,
                    "sha256": sha256,
                    "metadata": parsed_metadata,
                    "contentSource": {
                        "mode": "cached",
                        "locator": str(cached_path),
                        "details": {
                            "filename": original_name,
                            "sha256": sha256,
                            "sizeBytes": size_bytes,
                            "source": "desktop_upload",
                        },
                    },
                    "deliveryTarget": {
                        "type": "gateway_destination",
                        "destinationId": destination.id,
                        "integrationId": destination.integration_id,
                        "scopeId": destination.scope_id,
                        "platform": destination.platform,
                        "platformKey": destination.platform_key,
                        "displayName": destination.display_name,
                        "selector": destination.selector,
                        "path": object_identity,
                    },
                    "scanOnly": False,
                    **({"protectedEntity": protected_entity} if protected_entity is not None else {}),
                },
            }
        )
    request = BatchJobSubmitRequest(
        job_type="file.transfer",
        integration_id=destination.integration_id,
        scope_id=destination.scope_id,
        payload={
            "source": "desktop_transfer",
            "transferId": transfer_id,
            "destinationId": destination.id,
            "destination": destination.model_dump(mode="json"),
            "metadata": parsed_metadata,
            "attribution": attribution,
            "itemCount": len(items),
        },
        items=items,
    )
    batch = await run_in_threadpool(lambda: asyncio.run(job_service.submit_batch_job(request)))
    return GatewayTransferResponse(
        transfer_id=transfer_id,
        job_id=batch.job.job_id,
        state=batch.job.state,
        destination_id=destination.id,
        submitted_files=len(items),
        status_url=f"{settings.api_prefix}/execution/jobs/{batch.job.job_id}/progress",
        job=batch,
    )
