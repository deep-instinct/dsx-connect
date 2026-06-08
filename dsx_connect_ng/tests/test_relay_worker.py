import asyncio
import json
import sys
import time
import types

import pytest

from dsx_connect_ng.jobs.bus import InMemoryJobBus, JobBus
from dsx_connect_ng.jobs.models import BatchJobSubmitRequest, JobSubmitRequest, OutboxFlushResult
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.relay_worker import PostgresOutboxWakeListener, build_outbox_wake_listener, relay_forever, relay_once


class FailingJobBus(JobBus):
    async def publish(self, job) -> None:
        raise RuntimeError("broker unavailable")

    async def status(self) -> dict:
        return {"backend": "failing"}


class StopRelay(RuntimeError):
    pass


def test_relay_once_flushes_pending_outbox() -> None:
    repo = InMemoryJobRepository()
    service = JobService(repo=repo, bus=FailingJobBus())
    created = asyncio.run(
        service.submit_job(
            JobSubmitRequest(
                job_type="scan.requested",
                payload={"selector": "/finance/a.pdf"},
            )
        )
    )
    assert created.state == "publish_pending"

    recovery_bus = InMemoryJobBus()
    service.bus = recovery_bus
    result = asyncio.run(relay_once(service, limit=25))

    assert result.attempted == 1
    assert result.published == 1
    assert result.failed == 0
    reloaded = repo.get_job(created.job_id)
    assert reloaded is not None
    assert reloaded.state == "queued"
    assert len(recovery_bus.snapshot()) == 1


def test_relay_once_handles_empty_outbox() -> None:
    repo = InMemoryJobRepository()
    service = JobService(repo=repo, bus=InMemoryJobBus())

    result = asyncio.run(relay_once(service, limit=25))

    assert result.attempted == 0
    assert result.published == 0
    assert result.failed == 0


def test_relay_once_passes_active_scan_item_limit() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )

    first = asyncio.run(relay_once(service, limit=25, max_active_scan_items=1))
    second = asyncio.run(relay_once(service, limit=25, max_active_scan_items=1))

    assert first.attempted == 1
    assert first.published == 1
    assert second.attempted == 0
    assert second.publish_capacity == 0
    assert len(bus.snapshot()) == 1


def test_build_outbox_wake_listener_uses_postgres_backend(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.relay_worker.settings.postgres.url", "postgresql://example/db")

    listener = build_outbox_wake_listener({"job_repository_backend": "postgres"})

    assert listener is not None
    assert listener.db_url == "postgresql://example/db"


def test_build_outbox_wake_listener_uses_polling_for_non_postgres(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.relay_worker.settings.postgres.url", "postgresql://example/db")

    listener = build_outbox_wake_listener({"job_repository_backend": "memory"})

    assert listener is None


def test_postgres_outbox_wake_listener_uses_dedicated_listener_connection(monkeypatch) -> None:
    notifications: list[object] = []
    executed: list[str] = []

    class FakeConnection:
        closed = False

        def execute(self, query: str) -> None:
            executed.append(query)

        def notifies(self, *, timeout: float | None = None, stop_after: int | None = None):
            deadline = time.monotonic() + (timeout or 0)
            while time.monotonic() < deadline:
                if notifications:
                    yield notifications.pop(0)
                    return
                time.sleep(0.001)

        def close(self) -> None:
            self.closed = True

    fake_psycopg = types.SimpleNamespace(connect=lambda *args, **kwargs: FakeConnection())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    listener = PostgresOutboxWakeListener("postgresql://example/db")

    async def run() -> bool:
        await listener.start()
        notifications.append(object())
        try:
            return await listener.wait(1.0)
        finally:
            listener.close()

    assert asyncio.run(run()) is True
    assert executed == ["LISTEN dsx_ng_outbox"]


def test_relay_forever_logs_postgres_wakeup_result(capsys: pytest.CaptureFixture[str]) -> None:
    class FakeService:
        calls = 0

        async def flush_outbox(self, *, limit: int, max_active_scan_items: int | None = None) -> OutboxFlushResult:
            self.calls += 1
            if self.calls > 1:
                raise StopRelay()
            return OutboxFlushResult()

    class FakeWakeListener:
        closed = False

        async def start(self) -> None:
            return None

        async def wait(self, timeout_seconds: float) -> bool:
            return True

        def close(self) -> None:
            self.closed = True

    listener = FakeWakeListener()

    with pytest.raises(StopRelay):
        asyncio.run(
            relay_forever(
                FakeService(),
                limit=100,
                poll_interval_seconds=0.25,
                max_active_scan_items=None,
                wake_listener=listener,
            )
        )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    wakeup = next(event for event in events if event["event"] == "relay_wakeup")
    assert wakeup["notified"] is True
    assert wakeup["timeout_seconds"] == 0.25
    assert wakeup["elapsed_ms"] >= 0
    assert listener.closed is True


def test_relay_forever_drains_non_empty_flushes_without_wait(capsys: pytest.CaptureFixture[str]) -> None:
    class FakeService:
        calls = 0

        async def flush_outbox(self, *, limit: int, max_active_scan_items: int | None = None) -> OutboxFlushResult:
            self.calls += 1
            if self.calls == 1:
                return OutboxFlushResult(attempted=100, published=100)
            if self.calls == 2:
                raise StopRelay()
            return OutboxFlushResult()

    class FakeWakeListener:
        wait_calls = 0

        async def start(self) -> None:
            return None

        async def wait(self, timeout_seconds: float) -> bool:
            self.wait_calls += 1
            return False

        def close(self) -> None:
            return None

    listener = FakeWakeListener()

    with pytest.raises(StopRelay):
        asyncio.run(
            relay_forever(
                FakeService(),
                limit=100,
                poll_interval_seconds=0.25,
                max_active_scan_items=None,
                wake_listener=listener,
            )
        )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["event"] for event in events] == ["relay_flush"]
    assert listener.wait_calls == 0
