from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from shared.routes import API_PREFIX_V1, route_path
from shared.dsx_logging import dsx_logging


router = APIRouter(prefix=route_path(API_PREFIX_V1))


ScopeType = Literal["path", "identity"]
ScopeMode = Literal["full_scan", "monitor"]


class ProtectedScopeCreateRequest(BaseModel):
    integration_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    container: str = Field(min_length=1)
    scope_type: ScopeType
    resource: str = Field(min_length=1, description="Path prefix or stable identity.")
    filter: str = ""
    mode: ScopeMode = "monitor"
    remediation_action: str = "nothing"
    enabled: bool = True
    display_name: str = ""


class ScopeMatchRequest(BaseModel):
    integration_id: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    container: str = Field(min_length=1)
    scope_type: ScopeType
    resource: str = Field(min_length=1)


class ProtectedScopeView(BaseModel):
    scope_id: str
    integration_id: str
    platform: str
    container: str
    scope_type: ScopeType
    resource: str
    filter: str
    mode: ScopeMode
    remediation_action: str
    enabled: bool
    display_name: str
    created_at: str


@dataclass
class _ScopePreviewStore:
    scopes: dict[str, ProtectedScopeView] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _store(request: Request) -> _ScopePreviewStore:
    st = getattr(request.app.state, "scope_engine_preview_store", None)
    if st is None:
        st = _ScopePreviewStore()
        request.app.state.scope_engine_preview_store = st
    return st


def _pg_repo(request: Request):
    return getattr(request.app.state, "control_plane_repo", None)


def _preview_enabled(request: Request) -> None:
    cfg = getattr(request.app.state, "config", None)
    enabled = bool(getattr(getattr(cfg, "features", None), "enable_scope_engine_preview", False))
    if not enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scope_engine_preview_disabled")


def _canon_path(value: str) -> str:
    v = "/" + value.strip().strip("/")
    return v.rstrip("/") or "/"


def _is_overlap(a: ProtectedScopeView, b: ProtectedScopeView) -> bool:
    if (
        a.integration_id != b.integration_id
        or a.platform != b.platform
        or a.container != b.container
        or a.scope_type != b.scope_type
    ):
        return False

    if a.scope_type == "identity":
        return a.resource == b.resource

    ap = _canon_path(a.resource)
    bp = _canon_path(b.resource)
    return ap == bp or ap.startswith(bp + "/") or bp.startswith(ap + "/")


@router.get(route_path("scope-engine", "preview"))
async def scope_engine_preview_status(request: Request):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        return {
            "enabled": True,
            "mode": "preview_only",
            "scope_count": len(st.scopes),
            "postgres_mirror_attached": _pg_repo(request) is not None,
            "note": "Preview store is in-memory and does not affect current scan routing.",
        }


@router.get(route_path("scope-engine", "preview", "scopes"))
async def list_preview_scopes(request: Request, source: str = "memory", limit: int = 200):
    _preview_enabled(request)
    src = str(source or "memory").strip().lower()
    if src not in {"memory", "postgres"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_source")

    if src == "postgres":
        repo = _pg_repo(request)
        if repo is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="postgres_mirror_not_attached")
        try:
            items = await asyncio.to_thread(repo.list_scope_preview, limit)
            return {"source": "postgres", "items": items, "count": len(items)}
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"postgres_list_failed: {e}")

    st = _store(request)
    async with st.lock:
        return {
            "source": "memory",
            "items": sorted((v.model_dump() for v in st.scopes.values()), key=lambda x: x["created_at"]),
            "count": len(st.scopes),
        }


@router.post(route_path("scope-engine", "preview", "scopes"), status_code=status.HTTP_201_CREATED)
async def create_preview_scope(request: Request, body: ProtectedScopeCreateRequest):
    _preview_enabled(request)
    st = _store(request)

    now = datetime.now(timezone.utc).isoformat()
    candidate = ProtectedScopeView(
        scope_id=str(uuid4()),
        integration_id=body.integration_id.strip(),
        platform=body.platform.strip(),
        container=body.container.strip(),
        scope_type=body.scope_type,
        resource=body.resource.strip(),
        filter=body.filter or "",
        mode=body.mode,
        remediation_action=body.remediation_action or "nothing",
        enabled=body.enabled,
        display_name=body.display_name or "",
        created_at=now,
    )

    async with st.lock:
        for existing in st.scopes.values():
            if _is_overlap(candidate, existing):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "overlapping_scope",
                        "existing_scope_id": existing.scope_id,
                        "existing_resource": existing.resource,
                    },
                )
        st.scopes[candidate.scope_id] = candidate

    repo = _pg_repo(request)
    if repo is not None:
        try:
            await asyncio.to_thread(repo.upsert_scope_preview, candidate.model_dump())
        except Exception as e:
            dsx_logging.warning(f"Scope preview PostgreSQL mirror failed (create): {e}")

    return {"status": "created", "scope": candidate.model_dump()}


@router.delete(route_path("scope-engine", "preview", "scopes", "{scope_id}"))
async def delete_preview_scope(request: Request, scope_id: str):
    _preview_enabled(request)
    st = _store(request)
    async with st.lock:
        if scope_id not in st.scopes:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scope_not_found")
        doomed = st.scopes[scope_id]
        del st.scopes[scope_id]

    repo = _pg_repo(request)
    if repo is not None:
        try:
            await asyncio.to_thread(repo.delete_scope_preview, doomed.integration_id, doomed.scope_id)
        except Exception as e:
            dsx_logging.warning(f"Scope preview PostgreSQL mirror failed (delete): {e}")
    return {"status": "deleted", "scope_id": scope_id}


@router.post(route_path("scope-engine", "preview", "match"))
async def match_preview_scope(request: Request, body: ScopeMatchRequest):
    _preview_enabled(request)
    st = _store(request)
    probe = ProtectedScopeView(
        scope_id="probe",
        integration_id=body.integration_id.strip(),
        platform=body.platform.strip(),
        container=body.container.strip(),
        scope_type=body.scope_type,
        resource=body.resource.strip(),
        filter="",
        mode="monitor",
        remediation_action="nothing",
        enabled=True,
        display_name="",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    async with st.lock:
        matches = [v for v in st.scopes.values() if _is_overlap(probe, v) and v.enabled]

    if not matches:
        return {"matched": False, "scope": None}

    # Because overlap is blocked on create, this should remain deterministic.
    selected = matches[0]
    return {"matched": True, "scope": selected.model_dump(), "match_count": len(matches)}
