import asyncio

from dsx_connect_ng.jobs.bus import InMemoryJobBus
from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.jobs.models import DomainJobEnvelope


def test_in_memory_job_bus_publishes_and_snapshots() -> None:
    bus = InMemoryJobBus()
    job = DomainJobEnvelope(
        job_id="job-1",
        job_type="scan.requested",
        state="queued",
        integration_id="integration-1",
        payload={"object": "file-a"},
    )

    asyncio.run(bus.publish(job))

    snapshot = bus.snapshot()
    status = asyncio.run(bus.status())
    assert len(snapshot) == 1
    assert snapshot[0].job_id == "job-1"
    assert snapshot[0].job_type == "scan.requested"
    assert status == {
        "backend": "memory",
        "published_count": 1,
    }


def test_in_memory_job_bus_publishes_contract_message() -> None:
    bus = InMemoryJobBus()
    message = ScanItemRequested(
        job_id="job-2",
        job_item_id="item-2",
        object_identity="/finance/b.pdf",
    ).as_envelope()

    asyncio.run(bus.publish(message))

    snapshot = bus.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].message_type == "scan_item_requested"
    assert snapshot[0].job_item_id == "item-2"
