from dsx_connect_ng.jobs import bootstrap
from dsx_connect_ng.jobs.bus import InMemoryJobBus


def test_build_job_bus_memory_mode(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "job_bus_backend", "memory")

    result = bootstrap.bootstrap_job_bus()

    assert isinstance(result.bus, InMemoryJobBus)
    assert result.backend == "memory"
    assert result.detail == "configured_memory_mode"


def test_build_job_bus_rabbitmq_mode(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "job_bus_backend", "rabbitmq")

    class DummyRabbitMQBus:
        pass

    def fake_build_rabbitmq_bus():
        return DummyRabbitMQBus()

    monkeypatch.setattr(bootstrap, "_build_rabbitmq_bus", fake_build_rabbitmq_bus)
    result = bootstrap.bootstrap_job_bus()

    assert isinstance(result.bus, DummyRabbitMQBus)
    assert result.backend == "rabbitmq"
    assert result.detail == "configured_rabbitmq_mode"


def test_build_job_bus_auto_selects_rabbitmq_when_available(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "job_bus_backend", "auto")

    class DummyRabbitMQBus:
        pass

    def fake_build_rabbitmq_bus():
        return DummyRabbitMQBus()

    monkeypatch.setattr(bootstrap, "_build_rabbitmq_bus", fake_build_rabbitmq_bus)
    result = bootstrap.bootstrap_job_bus()

    assert isinstance(result.bus, DummyRabbitMQBus)
    assert result.backend == "rabbitmq"
    assert result.detail == "auto_selected_rabbitmq"


def test_build_job_bus_auto_falls_back_to_memory(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap.settings, "job_bus_backend", "auto")

    def fail_build_rabbitmq_bus():
        raise RuntimeError("rabbitmq unavailable")

    monkeypatch.setattr(bootstrap, "_build_rabbitmq_bus", fail_build_rabbitmq_bus)
    result = bootstrap.bootstrap_job_bus()

    assert isinstance(result.bus, InMemoryJobBus)
    assert result.backend == "memory_fallback"
    assert "rabbitmq unavailable" in (result.detail or "")
