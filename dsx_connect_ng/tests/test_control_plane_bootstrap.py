from dsx_connect_ng.control_plane import bootstrap
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository


def test_build_control_plane_service_memory_mode(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "control_plane_backend", "memory")
    result = bootstrap.bootstrap_control_plane()
    assert isinstance(result.service.repo, InMemoryControlPlaneRepository)
    assert result.backend == "memory"
    assert result.detail == "configured_memory_mode"


def test_build_control_plane_service_postgres_mode(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "control_plane_backend", "postgres")

    class DummyPostgresRepo:
        pass

    def fake_build_postgres_repo():
        return DummyPostgresRepo()

    monkeypatch.setattr(bootstrap, "_build_postgres_repo", fake_build_postgres_repo)
    result = bootstrap.bootstrap_control_plane()
    assert isinstance(result.service.repo, DummyPostgresRepo)
    assert result.backend == "postgres"
    assert result.detail == "configured_postgres_mode"


def test_build_control_plane_service_auto_falls_back_to_memory(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "control_plane_backend", "auto")

    def fail_build_postgres_repo():
        raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(bootstrap, "_build_postgres_repo", fail_build_postgres_repo)
    result = bootstrap.bootstrap_control_plane()
    assert isinstance(result.service.repo, InMemoryControlPlaneRepository)
    assert result.backend == "memory_fallback"
    assert "postgres unavailable" in (result.detail or "")
