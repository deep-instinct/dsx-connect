from __future__ import annotations

from dataclasses import dataclass

from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.bootstrap import ControlPlaneBootstrapResult
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.bus import InMemoryJobBus, JobBus
from dsx_connect_ng.jobs.repository import InMemoryJobRepository, JobRepository
from dsx_connect_ng.jobs.rabbitmq_bus import RabbitMQJobBus
from dsx_connect_ng.jobs.service import JobService


@dataclass(frozen=True)
class JobBusBootstrapResult:
    bus: JobBus
    backend: str
    detail: str | None = None


@dataclass(frozen=True)
class JobServiceBootstrapResult:
    service: JobService
    backend: str
    detail: str | None = None


def _build_rabbitmq_bus() -> RabbitMQJobBus:
    return RabbitMQJobBus(settings)


def bootstrap_job_bus() -> JobBusBootstrapResult:
    mode = settings.job_bus_backend
    if mode == "memory":
        return JobBusBootstrapResult(
            bus=InMemoryJobBus(),
            backend="memory",
            detail="configured_memory_mode",
        )
    if mode == "rabbitmq":
        return JobBusBootstrapResult(
            bus=_build_rabbitmq_bus(),
            backend="rabbitmq",
            detail="configured_rabbitmq_mode",
        )
    try:
        return JobBusBootstrapResult(
            bus=_build_rabbitmq_bus(),
            backend="rabbitmq",
            detail="auto_selected_rabbitmq",
        )
    except Exception as exc:
        return JobBusBootstrapResult(
            bus=InMemoryJobBus(),
            backend="memory_fallback",
            detail=f"auto_fallback:{type(exc).__name__}:{exc}",
        )


def _build_job_repo(control_plane_bootstrap: ControlPlaneBootstrapResult) -> JobRepository:
    if control_plane_bootstrap.backend == "postgres":
        from dsx_connect_ng.jobs.postgres_repo import PostgresJobRepository

        return PostgresJobRepository(settings.postgres.url)
    return InMemoryJobRepository()


def bootstrap_job_service(
    control_plane_bootstrap: ControlPlaneBootstrapResult,
    job_bus_bootstrap: JobBusBootstrapResult,
) -> JobServiceBootstrapResult:
    repo = _build_job_repo(control_plane_bootstrap)
    control_plane_service: ControlPlaneService | None = control_plane_bootstrap.service
    if control_plane_bootstrap.backend == "postgres":
        return JobServiceBootstrapResult(
            service=JobService(repo=repo, bus=job_bus_bootstrap.bus, control_plane=control_plane_service),
            backend="postgres",
            detail=f"follows_control_plane:{control_plane_bootstrap.backend}",
        )
    return JobServiceBootstrapResult(
        service=JobService(repo=repo, bus=job_bus_bootstrap.bus, control_plane=control_plane_service),
        backend="memory",
        detail=f"follows_control_plane:{control_plane_bootstrap.backend}",
    )
