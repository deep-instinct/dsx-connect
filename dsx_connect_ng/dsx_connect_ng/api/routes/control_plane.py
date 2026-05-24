from fastapi import APIRouter, Depends, Query, Request

from dsx_connect_ng.api.dependencies import get_control_plane_service
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.models import (
    IntegrationCreate,
    IntegrationRecord,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeRecord,
    ProtectedScopeUpdate,
)
from dsx_connect_ng.control_plane.service import ControlPlaneService

router = APIRouter(prefix="/control-plane", tags=["control-plane"])


@router.get("/status")
async def control_plane_status(request: Request) -> dict:
    bootstrap = getattr(request.app.state, "control_plane_bootstrap", None)
    return {
        "surface": "control-plane",
        "service": settings.service_name,
        "ownership": [
            "integrations",
            "protected_scopes",
            "policies",
            "job_metadata",
        ],
        "configured_backend_mode": settings.control_plane_backend,
        "postgres_url": settings.postgres.url,
        "backend": getattr(bootstrap, "backend", "unknown"),
        "backend_detail": getattr(bootstrap, "detail", None),
        "intended_callers": [
            "connectors",
            "backend_services",
            "operator_automation",
        ],
    }


@router.get("/integrations", response_model=list[IntegrationRecord])
async def list_integrations(
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> list[IntegrationRecord]:
    return service.list_integrations()


@router.post("/integrations", response_model=IntegrationRecord)
async def create_integration(
    payload: IntegrationCreate,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return service.create_integration(payload)


@router.get("/integrations/{integration_id}", response_model=IntegrationRecord)
async def get_integration(
    integration_id: str,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return service.get_integration_or_404(integration_id)


@router.patch("/integrations/{integration_id}", response_model=IntegrationRecord)
async def update_integration(
    integration_id: str,
    payload: IntegrationUpdate,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> IntegrationRecord:
    return service.update_integration(integration_id, payload)


@router.get("/scopes", response_model=list[ProtectedScopeRecord])
async def list_scopes(
    integration_id: str | None = Query(default=None),
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> list[ProtectedScopeRecord]:
    return service.list_scopes(integration_id=integration_id)


@router.post("/scopes", response_model=ProtectedScopeRecord)
async def create_scope(
    payload: ProtectedScopeCreate,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return service.create_scope(payload)


@router.get("/scopes/{scope_id}", response_model=ProtectedScopeRecord)
async def get_scope(
    scope_id: str,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return service.get_scope_or_404(scope_id)


@router.patch("/scopes/{scope_id}", response_model=ProtectedScopeRecord)
async def update_scope(
    scope_id: str,
    payload: ProtectedScopeUpdate,
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> ProtectedScopeRecord:
    return service.update_scope(scope_id, payload)


@router.get("/scope-match")
async def match_scope(
    integration_id: str = Query(...),
    scope_type: str = Query(...),
    resource_selector: str = Query(...),
    service: ControlPlaneService = Depends(get_control_plane_service),
) -> dict:
    matched = service.match_scope(
        integration_id=integration_id,
        scope_type=scope_type,
        resource_selector=resource_selector,
    )
    return {
        "integration_id": integration_id,
        "scope_type": scope_type,
        "resource_selector": resource_selector,
        "matched": matched.model_dump() if matched else None,
    }
