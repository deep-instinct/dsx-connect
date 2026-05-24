from dataclasses import dataclass

from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.control_plane.service import ControlPlaneService


@dataclass(frozen=True)
class ControlPlaneBootstrapResult:
    service: ControlPlaneService
    backend: str
    detail: str | None = None


def _build_postgres_repo():
    from dsx_connect_ng.control_plane.postgres_repo import PostgresControlPlaneRepository, apply_schema

    if not settings.postgres.url:
        raise RuntimeError("postgres_url_not_configured")
    if settings.postgres.auto_apply_schema:
        apply_schema(settings.postgres.url)
    return PostgresControlPlaneRepository(settings.postgres.url)


def bootstrap_control_plane() -> ControlPlaneBootstrapResult:
    mode = settings.control_plane_backend
    if mode == "memory":
        return ControlPlaneBootstrapResult(
            service=ControlPlaneService(repo=InMemoryControlPlaneRepository()),
            backend="memory",
            detail="configured_memory_mode",
        )
    if mode == "postgres":
        return ControlPlaneBootstrapResult(
            service=ControlPlaneService(repo=_build_postgres_repo()),
            backend="postgres",
            detail="configured_postgres_mode",
        )
    try:
        return ControlPlaneBootstrapResult(
            service=ControlPlaneService(repo=_build_postgres_repo()),
            backend="postgres",
            detail="auto_selected_postgres",
        )
    except Exception as exc:
        return ControlPlaneBootstrapResult(
            service=ControlPlaneService(repo=InMemoryControlPlaneRepository()),
            backend="memory_fallback",
            detail=f"auto_fallback:{type(exc).__name__}:{exc}",
        )


def build_control_plane_service() -> ControlPlaneService:
    return bootstrap_control_plane().service
