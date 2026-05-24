from dsx_connect_ng.control_plane.bootstrap import ControlPlaneBootstrapResult
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs import bootstrap
from dsx_connect_ng.jobs.bus import InMemoryJobBus
from dsx_connect_ng.jobs.repository import InMemoryJobRepository


def build_memory_control_plane_bootstrap() -> ControlPlaneBootstrapResult:
    return ControlPlaneBootstrapResult(
        service=ControlPlaneService(repo=InMemoryControlPlaneRepository()),
        backend="memory",
        detail="test_memory",
    )


def test_bootstrap_job_service_uses_memory_repo_when_control_plane_is_memory() -> None:
    result = bootstrap.bootstrap_job_service(
        build_memory_control_plane_bootstrap(),
        bootstrap.JobBusBootstrapResult(bus=InMemoryJobBus(), backend="memory"),
    )

    assert isinstance(result.service.repo, InMemoryJobRepository)
    assert result.backend == "memory"


def test_bootstrap_job_service_uses_postgres_repo_when_control_plane_is_postgres(monkeypatch) -> None:
    class DummyPostgresRepo:
        pass

    def fake_build_job_repo(_control_plane_bootstrap):
        return DummyPostgresRepo()

    monkeypatch.setattr(bootstrap, "_build_job_repo", fake_build_job_repo)
    result = bootstrap.bootstrap_job_service(
        ControlPlaneBootstrapResult(
            service=ControlPlaneService(repo=InMemoryControlPlaneRepository()),
            backend="postgres",
            detail="test_postgres",
        ),
        bootstrap.JobBusBootstrapResult(bus=InMemoryJobBus(), backend="memory"),
    )

    assert isinstance(result.service.repo, DummyPostgresRepo)
    assert result.backend == "postgres"
