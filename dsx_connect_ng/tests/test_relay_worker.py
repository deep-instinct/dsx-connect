import asyncio

from dsx_connect_ng.jobs.bus import InMemoryJobBus, JobBus
from dsx_connect_ng.jobs.models import JobSubmitRequest
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.relay_worker import relay_once


class FailingJobBus(JobBus):
    async def publish(self, job) -> None:
        raise RuntimeError("broker unavailable")

    async def status(self) -> dict:
        return {"backend": "failing"}


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
