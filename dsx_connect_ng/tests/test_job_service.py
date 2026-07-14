import asyncio

from fastapi import HTTPException

from dsx_connect_ng.config import RecoverySettings
from dsx_connect_ng.control_plane.models import IntegrationCreate, ProtectedScopeCreate
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.jobs.bus import InMemoryJobBus, JobBus
from dsx_connect_ng.jobs.contracts import MessageEnvelope

from dsx_connect_ng.jobs.models import BatchJobSubmitRequest, DeliveryRequest, DiannaAnalysisRequest, JobCreate, JobSubmitRequest, PolicyDecision, RemediationRequest, ScanResult, StageUpdateRequest
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService


class FailingJobBus(JobBus):
    async def publish(self, job) -> None:
        raise RuntimeError("broker down")

    async def status(self) -> dict:
        return {"backend": "failing"}


class CallbackJobBus(JobBus):
    def __init__(self, callback):
        self.callback = callback
        self.published: list[MessageEnvelope] = []

    async def publish(self, job) -> None:
        self.published.append(job)
        await self.callback(job)

    async def status(self) -> dict:
        return {"backend": "callback"}


class BulkCapableInMemoryJobRepository(InMemoryJobRepository):
    def create_job_items_and_outbox_records(self, *, job, job_items, topic: str, payloads: list[dict]) -> int:
        for item in job_items:
            self._job_items[item.job_item_id] = item
        for payload in payloads:
            self.create_outbox_record(job=job, topic=topic, payload=payload)
        return len(job_items)


class CountingJobRepository(InMemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.single_stage_updates = 0
        self.multi_stage_updates = 0
        self.bulk_stage_updates = 0
        self.job_state_updates = 0
        self.item_state_updates = 0
        self.bulk_outbox_claims = 0
        self.bulk_outbox_published = 0

    def update_job_item_stage(self, *args, **kwargs):
        self.single_stage_updates += 1
        return super().update_job_item_stage(*args, **kwargs)

    def update_job_item_stages(self, *args, **kwargs):
        self.multi_stage_updates += 1
        return super().update_job_item_stages(*args, **kwargs)

    def update_job_items_stages_bulk(self, *args, **kwargs):
        self.bulk_stage_updates += 1
        return super().update_job_items_stages_bulk(*args, **kwargs)

    def update_job_state(self, *args, **kwargs):
        self.job_state_updates += 1
        return super().update_job_state(*args, **kwargs)

    def update_job_item_state(self, *args, **kwargs):
        self.item_state_updates += 1
        return super().update_job_item_state(*args, **kwargs)

    def claim_outbox_records(self, outbox_ids):
        self.bulk_outbox_claims += 1
        return super().claim_outbox_records(outbox_ids)

    def mark_outbox_published_many(self, outbox_ids):
        self.bulk_outbox_published += 1
        return super().mark_outbox_published_many(outbox_ids)


def build_control_plane_service() -> ControlPlaneService:
    repo = InMemoryControlPlaneRepository()
    service = ControlPlaneService(repo=repo)
    service.create_integration(
        IntegrationCreate(
            integration_id="integration-a",
            platform="local",
            platform_key="integration-a",
            display_name="Integration A",
        )
    )
    service.create_integration(
        IntegrationCreate(
            integration_id="integration-b",
            platform="local",
            platform_key="integration-b",
            display_name="Integration B",
        )
    )
    service.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-a",
            integration_id="integration-a",
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="full_scan",
        )
    )
    return service


def test_submit_job_persists_and_queues() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_job(
            JobSubmitRequest(
                job_type="scan.requested",
                integration_id="integration-a",
                object_identity="/finance/a.pdf",
                payload={"selector": "/finance/a.pdf"},
            )
        )
    )

    assert created.state == "queued"
    assert repo.get_job(created.job_id) is not None
    assert len(bus.snapshot()) == 1
    assert bus.snapshot()[0].job_id == created.job_id
    assert bus.snapshot()[0].state == "queued"


def test_submit_job_honors_idempotency_key() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    request = JobSubmitRequest(
        job_type="scan.requested",
        idempotency_key="idem-1",
        payload={"selector": "/finance/a.pdf"},
    )

    first = asyncio.run(service.submit_job(request))
    second = asyncio.run(service.submit_job(request))

    assert first.job_id == second.job_id
    assert len(repo.list_jobs()) == 1
    assert len(bus.snapshot()) == 1


def test_submit_job_records_publish_pending_when_bus_fails() -> None:
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
    assert created.error is not None
    assert created.error["code"] == "job_publish_failed"


def test_flush_outbox_retries_pending_job_successfully() -> None:
    repo = InMemoryJobRepository()
    failing_bus = FailingJobBus()
    service = JobService(repo=repo, bus=failing_bus)

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
    flushed = asyncio.run(service.flush_outbox(limit=10))

    assert flushed.attempted == 1
    assert flushed.published == 1
    assert flushed.failed == 0
    assert len(flushed.records) == 1
    assert flushed.records[0].publish_state == "published"
    recovered = repo.get_job(created.job_id)
    assert recovered is not None
    assert recovered.state == "queued"
    assert len(recovery_bus.snapshot()) == 1


def test_flush_outbox_reports_failed_retry() -> None:
    repo = InMemoryJobRepository()
    service = JobService(repo=repo, bus=FailingJobBus())

    asyncio.run(
        service.submit_job(
            JobSubmitRequest(
                job_type="scan.requested",
                payload={"selector": "/finance/a.pdf"},
            )
        )
    )
    flushed = asyncio.run(service.flush_outbox(limit=10))

    assert flushed.attempted == 1
    assert flushed.published == 0
    assert flushed.failed == 1
    assert flushed.records[0].publish_state == "pending"


def test_publish_outbox_record_claim_prevents_duplicate_publish() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    job = repo.create_job(JobCreate(job_type="scan.requested", state="accepted"))
    outbox = repo.create_outbox_record(
        job=job,
        topic=job.job_type,
        payload=job.as_envelope(state_override="queued").model_dump(mode="json"),
    )

    first_published, first_record = asyncio.run(service._publish_outbox_record(outbox))
    second_published, second_record = asyncio.run(service._publish_outbox_record(outbox))

    assert first_published is True
    assert first_record.publish_state == "published"
    assert second_published is True
    assert second_record.publish_state == "published"
    assert len(bus.snapshot()) == 1


def test_submit_batch_job_creates_parent_and_items() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                integration_id="integration-a",
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"selector": "/finance/a.pdf"}},
                    {"object_identity": "/finance/b.pdf", "payload": {"selector": "/finance/b.pdf"}},
                ],
            )
        )
    )

    assert created.job.state == "queued"
    assert created.item_summary.total == 2
    assert created.item_summary.queued == 2
    items = service.list_job_items(job_id=created.job.job_id)
    assert len(items) == 2
    assert len(bus.snapshot()) == 2
    assert all(getattr(envelope, "message_type", None) == "scan_item_requested" for envelope in bus.snapshot())
    assert all(envelope.job_item_id for envelope in bus.snapshot())
    assert bus.snapshot()[0].payload["scan_options"]["selector"] == "/finance/a.pdf"
    assert bus.snapshot()[0].payload["content_source"]["mode"] == "original"
    assert created.job.effective_recovery_mode == "batch"
    assert created.job.recovery_mode_requested is None
    assert created.job.recovery_policy_snapshot is not None
    assert created.job.recovery_policy_snapshot["source"] == "settings_default"


def test_connector_batch_without_scope_uses_matching_protected_scope() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    control_plane = build_control_plane_service()
    service = JobService(repo=repo, bus=bus, control_plane=control_plane)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                integration_id="integration-a",
                payload={"source": "connector_monitor"},
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"selector": "/finance/a.pdf"}},
                    {"object_identity": "/finance/b.pdf", "payload": {"selector": "/finance/b.pdf"}},
                ],
            )
        )
    )

    assert created.job.scope_id == "scope-a"
    assert {envelope.scope_id for envelope in bus.snapshot()} == {"scope-a"}


def test_connector_batch_without_scope_does_not_infer_mixed_scopes() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    control_plane = build_control_plane_service()
    control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-b-hr",
            integration_id="integration-a",
            scope_type="path",
            resource_selector="/hr",
            display_name="HR",
            mode="full_scan",
        )
    )
    service = JobService(repo=repo, bus=bus, control_plane=control_plane)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                integration_id="integration-a",
                payload={"source": "connector_monitor"},
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/hr/b.pdf"},
                ],
            )
        )
    )

    assert created.job.scope_id is None
    assert {envelope.scope_id for envelope in bus.snapshot()} == {None}


def test_submit_batch_job_can_defer_publish_to_outbox_relay() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
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

    assert created.job.state == "publish_pending"
    assert created.job.error == {"code": "batch_publish_pending"}
    assert created.item_summary.total == 2
    assert created.item_summary.publish_pending == 2
    assert bus.snapshot() == []
    assert len(repo.list_outbox_records(publish_state="pending")) == 2

    flushed = asyncio.run(service.flush_outbox(limit=2))
    refreshed = service.get_batch_job_or_404(created.job.job_id)

    assert flushed.published == 2
    assert refreshed.job.state == "queued"
    assert refreshed.job.error is None
    assert refreshed.item_summary.queued == 2
    assert len(bus.snapshot()) == 2


def test_flush_outbox_uses_bulk_state_updates_for_low_persistence_scan_only_batch() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": f"/finance/{index}.pdf", "payload": {"scanOnly": True}}
                    for index in range(5)
                ],
            )
        )
    )

    flushed = asyncio.run(service.flush_outbox(limit=5))

    assert flushed.published == 5
    assert len(bus.snapshot()) == 5
    assert repo.bulk_outbox_claims == 1
    assert repo.bulk_outbox_published == 1
    refreshed = service.get_batch_job_or_404(created.job.job_id)
    assert refreshed.item_summary.publish_pending == 5


def test_scan_publish_does_not_regress_fast_completed_scan_only_item() -> None:
    repo = InMemoryJobRepository()
    service: JobService

    async def complete_during_publish(envelope: MessageEnvelope) -> None:
        if envelope.message_type != "scan_item_requested" or envelope.job_item_id is None:
            return
        service.complete_scan_only(
            envelope.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )

    bus = CallbackJobBus(complete_during_publish)
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {"scanOnly": True},
                    }
                ],
            )
        )
    )

    flushed = asyncio.run(service.flush_outbox(limit=1))

    assert flushed.published == 1
    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"
    assert item.scan_stage.state == "completed"
    assert item.delivery_stage.state == "skipped"


def test_replay_nonterminal_scan_only_batch_requeues_missing_scan_outbox() -> None:
    repo = BulkCapableInMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                ],
            )
        )
    )
    asyncio.run(service.flush_outbox(limit=10))
    first, second = service.list_job_items(job_id=created.job.job_id)
    service.complete_scan_only(
        first.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
    )

    replayed = service.replay_nonterminal_scan_only_batches()

    assert replayed == 1
    refreshed = service.list_job_items(job_id=created.job.job_id)
    assert refreshed[0].state == "completed"
    assert refreshed[1].state == "publish_pending"
    assert refreshed[1].error == {"code": "scan_only_batch_replay"}
    pending = repo.list_outbox_records(publish_state="pending")
    assert len(pending) == 1
    assert pending[0].payload["job_item_id"] == second.job_item_id


def test_replay_nonterminal_scan_only_batch_does_not_duplicate_pending_outbox() -> None:
    repo = BulkCapableInMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                ],
            )
        )
    )

    replayed = service.replay_nonterminal_scan_only_batches()

    assert replayed == 0
    assert len(repo.list_outbox_records(publish_state="pending")) == 2
    refreshed = service.get_batch_job_or_404(created.job.job_id)
    assert refreshed.item_summary.publish_pending == 2


def test_submit_batch_job_defaults_to_deferred_publish_when_bulk_outbox_is_available() -> None:
    repo = BulkCapableInMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )

    assert created.job.state == "publish_pending"
    assert created.job.error == {"code": "batch_publish_pending"}
    assert created.item_summary.publish_pending == 2
    assert bus.snapshot() == []
    assert len(repo.list_outbox_records(publish_state="pending")) == 2


def test_submit_batch_job_can_force_immediate_publish_when_bulk_outbox_is_available() -> None:
    repo = BulkCapableInMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "immediate"},
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )

    assert created.job.state == "queued"
    assert created.item_summary.queued == 2
    assert len(bus.snapshot()) == 2


def test_flush_outbox_respects_active_scan_item_limit() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                    {"object_identity": "/finance/c.pdf"},
                ],
            )
        )
    )

    first_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    blocked_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    refreshed = service.get_batch_job_or_404(created.job.job_id)

    assert first_flush.attempted == 2
    assert first_flush.published == 2
    assert first_flush.active_scan_items == 0
    assert first_flush.publish_capacity == 2
    assert blocked_flush.attempted == 0
    assert blocked_flush.active_scan_items == 2
    assert blocked_flush.publish_capacity == 0
    assert refreshed.item_summary.queued == 2
    assert refreshed.item_summary.publish_pending == 1
    assert len(bus.snapshot()) == 2


def test_flush_outbox_active_limit_ignores_coarse_scan_only_queued_rows() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/c.pdf", "payload": {"scanOnly": True}},
                ],
            )
        )
    )

    first_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    second_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    refreshed = service.get_batch_job_or_404(created.job.job_id)

    assert first_flush.attempted == 2
    assert first_flush.published == 2
    assert second_flush.attempted == 1
    assert second_flush.published == 1
    assert second_flush.active_scan_items == 0
    assert second_flush.publish_capacity == 2
    assert refreshed.item_summary.queued == 0
    assert refreshed.item_summary.publish_pending == 3
    assert len(bus.snapshot()) == 3
    assert repo.item_state_updates == 0


def test_flush_outbox_active_limit_counts_item_recovery_scan_only_queued_rows() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                recovery_mode="item",
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/c.pdf", "payload": {"scanOnly": True}},
                ],
            )
        )
    )

    first_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    blocked_flush = asyncio.run(service.flush_outbox(limit=10, max_active_scan_items=2))
    refreshed = service.get_batch_job_or_404(created.job.job_id)

    assert first_flush.attempted == 2
    assert first_flush.published == 2
    assert blocked_flush.attempted == 0
    assert blocked_flush.active_scan_items == 2
    assert blocked_flush.publish_capacity == 0
    assert refreshed.item_summary.queued == 2
    assert refreshed.item_summary.publish_pending == 1
    assert len(bus.snapshot()) == 2


def test_flush_outbox_publishes_fairly_across_deferred_jobs() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/old/a.pdf"},
                    {"object_identity": "/old/b.pdf"},
                    {"object_identity": "/old/c.pdf"},
                ],
            )
        )
    )
    asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[
                    {"object_identity": "/new/a.pdf"},
                    {"object_identity": "/new/b.pdf"},
                ],
            )
        )
    )

    flushed = asyncio.run(service.flush_outbox(limit=3))
    published_objects = [message.object_identity for message in bus.snapshot()]

    assert flushed.published == 3
    assert published_objects == ["/old/a.pdf", "/new/a.pdf", "/old/b.pdf"]


def test_cancel_job_marks_queued_backlog_cancelled() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )

    cancelled = service.cancel_job(created.job.job_id)

    assert cancelled.job.state == "cancelled"
    assert cancelled.item_summary.cancelled == 2
    assert all(item.error["code"] == "job_cancelled" for item in service.list_job_items(job_id=created.job.job_id))


def test_cancel_job_marks_scanning_items_cancelled() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/a.pdf"}]))
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="running"))

    cancelled = service.cancel_job(created.job.job_id)
    refreshed = service.list_job_items(job_id=created.job.job_id)[0]

    assert cancelled.job.state == "cancelled"
    assert refreshed.state == "cancelled"
    assert refreshed.error["code"] == "job_cancelled"


def test_flush_outbox_skips_cancelled_deferred_items() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                payload={"publishMode": "deferred"},
                items=[{"object_identity": "/finance/a.pdf"}],
            )
        )
    )
    service.cancel_job(created.job.job_id)

    flushed = asyncio.run(service.flush_outbox(limit=10))
    refreshed = service.get_batch_job_or_404(created.job.job_id)

    assert flushed.published == 1
    assert bus.snapshot() == []
    assert refreshed.job.state == "cancelled"
    assert refreshed.item_summary.cancelled == 1


def test_job_progress_reports_counts_throughput_and_latency() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    first_item = service.list_job_items(job_id=created.job.job_id)[0]
    asyncio.run(service.advance_scan_stage(first_item.job_item_id, StageUpdateRequest(state="running")))
    asyncio.run(
        service.advance_scan_stage(
            first_item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result=ScanResult(verdict="Benign", scanGuid="scan-1").model_dump(mode="json"),
                metadata={
                    "readerElapsedMs": 10.0,
                    "dsxaElapsedMs": 120.0,
                    "requestElapsedMs": 140.0,
                    "scannerEngineElapsedMs": 1.0,
                    "streamReadElapsedMs": 25.0,
                    "scannerResponseWaitElapsedMs": 95.0,
                },
            ),
        )
    )

    snapshot = service.get_job_progress(created.job.job_id)

    assert snapshot.job_id == created.job.job_id
    assert snapshot.total_items == 2
    assert snapshot.terminal_items == 0
    assert snapshot.percent_complete == 0.0
    assert snapshot.item_summary.scanned == 1
    assert snapshot.item_summary.queued == 1
    assert snapshot.backlog.queued == 1
    assert snapshot.latency.reader_elapsed_ms.avg_ms == 10.0
    assert snapshot.latency.stream_read_elapsed_ms.avg_ms == 25.0
    assert snapshot.latency.scanner_response_wait_elapsed_ms.avg_ms == 95.0
    assert snapshot.latency.scanner_engine_elapsed_ms.avg_ms == 1.0
    assert snapshot.latency.dsxa_elapsed_ms.avg_ms == 120.0
    assert snapshot.latency.request_elapsed_ms.avg_ms == 140.0
    assert snapshot.throughput.total.completed_items == 0
    assert snapshot.derived_from_item_count == 2
    assert any(hint.code == "scanner_api_latency_dominates" for hint in snapshot.bottleneck_hints)


def test_job_progress_reports_runtime_scan_leases_without_durable_scanning_state() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    service.mark_scan_runtime_started(job_id=created.job.job_id, job_item_id=item.job_item_id)
    snapshot = service.get_job_progress(created.job.job_id)

    assert snapshot.item_summary.scanning == 0
    assert snapshot.runtime.scan_leases_active == 1
    assert snapshot.backlog.scanning == 1


def test_job_progress_reports_terminal_percent_and_recent_throughput() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    for item in service.list_job_items(job_id=created.job.job_id):
        asyncio.run(service.advance_scan_stage(item.job_item_id, StageUpdateRequest(state="running")))
        asyncio.run(
            service.advance_scan_stage(
                item.job_item_id,
                StageUpdateRequest(
                    state="completed",
                    result=ScanResult(verdict="Benign", scanGuid=f"scan-{item.item_index}").model_dump(mode="json"),
                ),
            )
        )
        service.update_delivery_stage(item.job_item_id, StageUpdateRequest(state="skipped"))

    snapshot = service.get_job_progress(created.job.job_id)

    assert snapshot.total_items == 2
    assert snapshot.terminal_items == 2
    assert snapshot.percent_complete == 100.0
    assert snapshot.throughput.total.completed_items == 2
    assert snapshot.throughput.total.items_per_second is not None
    assert snapshot.throughput.recent_60s.completed_items == 2
    assert snapshot.throughput.total.terminal_items == 2
    assert snapshot.throughput.total.cancelled_items == 0


def test_job_progress_reports_cancelled_items_separately_from_completed_items() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)
    service.update_scan_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))
    service.update_remediation_stage(items[0].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))
    service.cancel_job(created.job.job_id)

    snapshot = service.get_job_progress(created.job.job_id)

    assert snapshot.terminal_items == 2
    assert snapshot.item_summary.completed == 1
    assert snapshot.item_summary.cancelled == 1
    assert snapshot.throughput.total.completed_items == 1
    assert snapshot.throughput.total.cancelled_items == 1
    assert snapshot.throughput.total.terminal_items == 2


def test_refresh_parent_preserves_cancelled_job_state() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)
    service.cancel_job(created.job.job_id)

    service.update_scan_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))
    service.update_remediation_stage(items[0].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))

    refreshed = service.get_job_or_404(created.job.job_id)
    assert refreshed.state == "cancelled"
    assert refreshed.error is not None
    assert refreshed.error["code"] == "job_cancelled"


def test_job_progress_recent_throughput_is_not_limited_to_sampled_items() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                    {"object_identity": "/finance/c.pdf"},
                ],
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)
    service.update_scan_stage(items[2].job_item_id, StageUpdateRequest(state="completed"))
    service.update_remediation_stage(items[2].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(items[2].job_item_id, StageUpdateRequest(state="completed"))

    snapshot = service.get_job_progress(created.job.job_id, item_limit=1)

    assert snapshot.derived_from_item_count == 1
    assert snapshot.throughput.total.completed_items == 1
    assert snapshot.throughput.recent_60s.completed_items == 1
    assert snapshot.throughput.recent_60s.terminal_items == 1


def test_submit_batch_job_persists_requested_recovery_mode() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                recovery_mode="item",
                items=[{"object_identity": "/finance/a.pdf"}],
            )
        )
    )

    assert created.job.recovery_mode_requested == "item"
    assert created.job.effective_recovery_mode == "item"
    assert created.job.recovery_policy_snapshot is not None
    assert created.job.recovery_policy_snapshot["source"] == "request"


def test_submit_batch_job_includes_effective_recovery_mode_in_scan_request() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)

    asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                recovery_mode="item",
                items=[{"object_identity": "/finance/a.pdf"}],
            )
        )
    )

    message = bus.snapshot()[0]

    assert isinstance(message, MessageEnvelope)
    assert message.message_type == "scan_item_requested"
    assert message.payload["scan_options"]["effectiveRecoveryMode"] == "item"


def test_submit_batch_job_resolves_adaptive_recovery_mode_once() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus, recovery_settings=RecoverySettings(mode="adaptive"))

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[{"object_identity": "/finance/a.pdf"}],
            )
        )
    )

    assert created.job.recovery_mode_requested is None
    assert created.job.effective_recovery_mode == "batch"
    assert created.job.recovery_policy_snapshot is not None
    assert created.job.recovery_policy_snapshot["source"] == "settings_adaptive_default"
    assert created.job.recovery_policy_snapshot["configuredMode"] == "adaptive"


def test_submit_batch_job_tracks_partial_publish_failure() -> None:
    repo = InMemoryJobRepository()
    service = JobService(repo=repo, bus=FailingJobBus())

    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )

    assert created.job.state == "publish_pending"
    assert created.item_summary.total == 2
    assert created.item_summary.publish_pending == 2


def test_submit_batch_job_honors_idempotency_key() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    request = BatchJobSubmitRequest(
        idempotency_key="batch-idem-1",
        items=[{"object_identity": "/finance/a.pdf"}],
    )

    first = asyncio.run(service.submit_batch_job(request))
    second = asyncio.run(service.submit_batch_job(request))

    assert first.job.job_id == second.job.job_id
    assert len(repo.list_jobs()) == 1
    assert len(service.list_job_items(job_id=first.job.job_id)) == 1


def test_submit_batch_job_rejects_unknown_integration() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus, control_plane=build_control_plane_service())

    try:
        asyncio.run(
            service.submit_batch_job(
                BatchJobSubmitRequest(
                    integration_id="missing-integration",
                    items=[{"object_identity": "/finance/a.pdf"}],
                )
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "integration_not_found"
    else:
        raise AssertionError("expected integration_not_found")


def test_submit_batch_job_rejects_scope_integration_mismatch() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus, control_plane=build_control_plane_service())

    try:
        asyncio.run(
            service.submit_batch_job(
                BatchJobSubmitRequest(
                    integration_id="integration-b",
                    scope_id="scope-a",
                    items=[{"object_identity": "/finance/a.pdf"}],
                )
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "scope_integration_mismatch"
    else:
        raise AssertionError("expected scope_integration_mismatch")


def test_flush_outbox_keeps_parent_publish_pending_until_all_items_retry() -> None:
    repo = InMemoryJobRepository()
    service = JobService(repo=repo, bus=FailingJobBus())
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    assert created.job.state == "publish_pending"

    pending = repo.list_outbox_records(publish_state="pending")
    assert len(pending) == 2
    recovery_bus = InMemoryJobBus()
    service.bus = recovery_bus
    flushed = asyncio.run(service.flush_outbox(limit=1))

    assert flushed.attempted == 1
    parent = repo.get_job(created.job.job_id)
    assert parent is not None
    assert parent.state == "publish_pending"


def test_update_job_item_state_moves_parent_to_running_and_completed() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)

    running = service.update_scan_stage(items[0].job_item_id, StageUpdateRequest(state="running"))
    assert running.state == "scanning"
    assert running.scan_stage.state == "running"
    parent = repo.get_job(created.job.job_id)
    assert parent is not None
    assert parent.state == "running"

    service.update_scan_stage(
        items[0].job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign"}),
    )
    interim_parent = repo.get_job(created.job.job_id)
    assert interim_parent is not None
    assert interim_parent.state == "queued"
    rescanned_item = repo.get_job_item(items[0].job_item_id)
    assert rescanned_item is not None
    assert rescanned_item.state == "scanned"

    service.update_scan_stage(items[1].job_item_id, StageUpdateRequest(state="completed"))
    service.update_remediation_stage(items[0].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_remediation_stage(items[1].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))
    service.update_delivery_stage(items[1].job_item_id, StageUpdateRequest(state="completed"))
    completed_parent = repo.get_job(created.job.job_id)
    assert completed_parent is not None
    assert completed_parent.state == "completed"
    batch = service.get_batch_job_or_404(created.job.job_id)
    assert batch.item_summary.completed == 2


def test_update_job_item_state_marks_parent_failed_when_terminal_failures_exist() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf"},
                    {"object_identity": "/finance/b.pdf"},
                ],
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)

    service.update_scan_stage(items[0].job_item_id, StageUpdateRequest(state="completed"))
    service.update_scan_stage(items[1].job_item_id, StageUpdateRequest(state="completed"))
    service.update_remediation_stage(
        items[0].job_item_id,
        StageUpdateRequest(state="failed", error={"code": "remediation_failed"}),
    )
    parent = repo.get_job(created.job.job_id)
    assert parent is not None
    assert parent.state == "queued"

    service.update_remediation_stage(items[1].job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(items[1].job_item_id, StageUpdateRequest(state="completed"))
    failed_parent = repo.get_job(created.job.job_id)
    assert failed_parent is not None
    assert failed_parent.state == "failed"
    assert failed_parent.error is not None
    assert failed_parent.error["code"] == "batch_item_failures"


def test_stage_updates_capture_timing_and_result() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[{"object_identity": "/finance/a.pdf"}],
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    running = service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="running"))
    assert running.scan_stage.started_at is not None
    completed = service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"scanGuid": "scan-1", "verdict": "Benign"}),
    )
    assert completed.scan_stage.completed_at is not None
    assert completed.scan_stage.result is not None
    assert completed.scan_stage.result["scanGuid"] == "scan-1"


def test_request_dianna_analysis_publishes_optional_branch_message() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "scan-1"}),
    )

    updated = asyncio.run(
        service.request_dianna_analysis(
            item.job_item_id,
            DiannaAnalysisRequest(reason="manual", payload={"priority": "low"}),
        )
    )

    assert updated.scan_stage.result is not None
    assert len(bus.snapshot()) == 2
    assert bus.snapshot()[-1].message_type == "dianna_analysis_requested"
    assert bus.snapshot()[-1].payload["request_reason"] == "manual"


def test_request_remediation_publishes_typed_message() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious", "scanGuid": "scan-2"}),
    )

    updated = asyncio.run(
        service.request_remediation(
            item.job_item_id,
            RemediationRequest(remediation_plan={"action": "quarantine"}),
        )
    )

    assert updated.state == "queued"
    assert bus.snapshot()[-1].message_type == "remediation_requested"
    assert bus.snapshot()[-1].integration_id is None
    assert bus.snapshot()[-1].scope_id is None
    assert bus.snapshot()[-1].payload["content_source"]["mode"] == "original"
    assert bus.snapshot()[-1].payload["remediation_plan"]["action"] == "quarantine"
    assert bus.snapshot()[-1].payload["scan_result"]["scanGuid"] == "scan-2"


def test_scan_completion_does_not_auto_publish_policy_evaluation_request() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/a.pdf"}])))
    item = service.list_job_items(job_id=created.job.job_id)[0]

    updated = asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign"}),
        )
    )

    assert updated.state == "scanned"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "policy_evaluation_requested" not in published_types


def test_delivery_completion_marks_item_completed_when_no_remediation_was_requested() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/good.pdf",
                        "payload": {
                            "policyDecision": {
                                "delivery_target": {"connector": "filesystem-local"},
                            }
                        },
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )
    )
    asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={"delivery_target": {"connector": "filesystem-local"}},
            ),
        )
    )

    current = service.get_job_item_or_404(item.job_item_id)
    assert current.state == "deliver_pending"
    assert current.remediation_stage.state == "skipped"
    assert current.remediation_stage.result == {"reason": "benign_verdict"}
    assert current.dianna_stage.state == "skipped"
    assert current.dianna_stage.result == {"reason": "not_auto_requested", "details": {"verdict": "Benign"}}

    completed = asyncio.run(
        service.advance_delivery_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={"destination": "filesystem-local", "outcome": "delivered"},
            ),
        )
    )

    assert completed.state == "completed"
    assert completed.delivery_stage.state == "completed"
    parent = service.get_batch_job_or_404(created.job.job_id)
    assert parent.job.state == "completed"


def test_request_dianna_analysis_rejects_non_malicious_items() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/good.pdf"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign"}),
    )

    try:
        asyncio.run(
            service.request_dianna_analysis(
                item.job_item_id,
                DiannaAnalysisRequest(reason="manual"),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "dianna_not_applicable_for_non_malicious_scan"
    else:
        raise AssertionError("expected DIANNA request rejection for benign item")


def test_request_dianna_analysis_rejects_missing_content_source() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    repo._job_items[item.job_item_id] = item.model_copy(
        update={"content_source": item.content_source.model_copy(update={"mode": "none", "locator": None})}
    )
    service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious"}),
    )

    try:
        asyncio.run(
            service.request_dianna_analysis(
                item.job_item_id,
                DiannaAnalysisRequest(reason="manual"),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "dianna_requires_available_content_source"
    else:
        raise AssertionError("expected DIANNA request rejection for missing content source")


def test_dianna_stage_is_independent_from_parent_completion() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Malicious"}),
    )
    service.update_remediation_stage(item.job_item_id, StageUpdateRequest(state="skipped"))
    service.update_delivery_stage(item.job_item_id, StageUpdateRequest(state="completed"))
    parent = repo.get_job(created.job.job_id)
    assert parent is not None
    assert parent.state == "completed"

    updated = service.update_dianna_stage(item.job_item_id, StageUpdateRequest(state="running"))
    assert updated.dianna_stage.state == "running"
    parent_after = repo.get_job(created.job.job_id)
    assert parent_after is not None
    assert parent_after.state == "completed"


def test_request_result_delivery_emits_combined_result() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/a.pdf"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="completed", result={"verdict": "Benign"}))
    service.update_remediation_stage(item.job_item_id, StageUpdateRequest(state="skipped"))

    updated = asyncio.run(
        service.request_result_delivery(
            item.job_item_id,
            DeliveryRequest(delivery_target={"connector": "sharepoint"}),
        )
    )

    assert updated.state == "deliver_pending"
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"
    assert bus.snapshot()[-1].payload["final_result"]["scan"]["verdict"] == "Benign"
    assert bus.snapshot()[-1].payload["final_result"]["remediation"] == {}
    assert bus.snapshot()[-1].payload["final_result"]["contentSource"]["mode"] == "original"
    assert bus.snapshot()[-1].payload["delivery_target"]["connector"] == "sharepoint"


def test_policy_completion_can_emit_scan_result_delivery_from_handoff_policy() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )
    )
    asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={
                    "policy_stage_result": {"policy_id": "policy-1"},
                    "remediation": {"state": "skipped", "reason": "benign_verdict"},
                    "dianna": {"state": "skipped", "reason": "not_auto_requested", "details": {"verdict": "Benign"}},
                    "delivery": {
                        "request_now": True,
                        "wait_for_dianna": False,
                        "scan_targets": [{"connector": "scan-sharepoint"}],
                        "workflow_summary_targets": [{"connector": "summary-sharepoint"}],
                    },
                    "content_preservation": {"mode": "none", "reason": "not_needed"},
                    "result_delivery_policy": {
                        "scan": "all_results",
                        "remediation": "all_outcomes",
                        "dianna": "completed_only",
                    },
                },
            ),
        )
    )

    deliveries = [
        message
        for message in bus.snapshot()
        if isinstance(message, MessageEnvelope) and message.message_type == "result_sink_emit_requested"
    ]
    assert any(message.payload.get("result_type") == "scan_result" for message in deliveries)
    scan_delivery = next(message for message in deliveries if message.payload.get("result_type") == "scan_result")
    assert scan_delivery.payload["result_payload"]["scanGuid"] == "scan-1"
    assert scan_delivery.payload["delivery_target"]["connector"] == "scan-sharepoint"
    summary_delivery = next(message for message in deliveries if message.payload.get("result_type") == "workflow_summary")
    assert summary_delivery.payload["delivery_target"]["connector"] == "summary-sharepoint"


def test_policy_completion_can_finish_with_scan_result_only_and_skip_workflow_summary() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )
    )
    updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={
                    "policy_stage_result": {"policy_id": "policy-1"},
                    "remediation": {"state": "skipped", "reason": "benign_verdict"},
                    "dianna": {"state": "skipped", "reason": "not_auto_requested", "details": {"verdict": "Benign"}},
                    "delivery": {
                        "request_now": False,
                        "wait_for_dianna": False,
                        "targets": [{"connector": "legacy-summary"}],
                        "scan_targets": [{"connector": "scan-sharepoint"}],
                        "scan_targets_configured": True,
                        "workflow_summary_targets": [],
                        "workflow_summary_targets_configured": True,
                    },
                    "content_preservation": {"mode": "none", "reason": "not_needed"},
                    "result_delivery_policy": {
                        "scan": "all_results",
                        "remediation": "all_outcomes",
                        "dianna": "completed_only",
                    },
                },
            ),
        )
    )

    deliveries = [
        message
        for message in bus.snapshot()
        if isinstance(message, MessageEnvelope) and message.message_type == "result_sink_emit_requested"
    ]
    assert len(deliveries) == 1
    assert deliveries[0].payload["result_type"] == "scan_result"
    assert updated.delivery_stage.state == "skipped"
    assert updated.delivery_stage.result == {
        "reason": "auxiliary_result_delivery_not_required",
        "result_type": "scan_result",
    }
    assert updated.state == "completed"


def test_scan_only_policy_completion_uses_single_multi_stage_update() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )
    )
    repo.single_stage_updates = 0
    repo.multi_stage_updates = 0

    updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={
                    "policy_stage_result": {"policy_id": "policy-1"},
                    "remediation": {"state": "skipped", "reason": "benign_verdict"},
                    "dianna": {"state": "skipped", "reason": "not_auto_requested", "details": {"verdict": "Benign"}},
                    "delivery": {
                        "request_now": False,
                        "wait_for_dianna": False,
                        "scan_targets": [{"connector": "scan-sharepoint"}],
                        "scan_targets_configured": True,
                        "workflow_summary_targets": [],
                        "workflow_summary_targets_configured": True,
                    },
                    "content_preservation": {"mode": "none", "reason": "not_needed"},
                    "result_delivery_policy": {
                        "scan": "all_results",
                        "remediation": "all_outcomes",
                        "dianna": "completed_only",
                    },
                },
            ),
        )
    )

    assert updated.state == "completed"
    assert repo.single_stage_updates == 0
    assert repo.multi_stage_updates == 1


def test_late_policy_running_update_does_not_regress_completed_item() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
        )
    )
    completed = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result={
                    "policy_stage_result": {"policy_id": "policy-1"},
                    "remediation": {"state": "skipped", "reason": "benign_verdict"},
                    "dianna": {"state": "skipped", "reason": "not_auto_requested", "details": {"verdict": "Benign"}},
                    "delivery": {
                        "request_now": False,
                        "wait_for_dianna": False,
                        "workflow_summary_targets": [],
                        "workflow_summary_targets_configured": True,
                    },
                    "content_preservation": {"mode": "none", "reason": "not_needed"},
                    "result_delivery_policy": {
                        "scan": "never",
                        "remediation": "all_outcomes",
                        "dianna": "completed_only",
                    },
                },
            ),
        )
    )

    regressed = service.update_policy_stage(item.job_item_id, StageUpdateRequest(state="running"))

    assert completed.state == "completed"
    assert completed.policy_stage.state == "completed"
    assert regressed.state == "completed"
    assert regressed.policy_stage.state == "completed"
    assert regressed.remediation_stage.state == "skipped"
    assert regressed.delivery_stage.state == "skipped"


def test_complete_scan_only_defers_parent_refresh_until_progress_poll() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {"scanOnly": True},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    repo.job_state_updates = 0

    updated = service.complete_scan_only(
        item.job_item_id,
        StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
    )

    assert updated.state == "completed"
    assert repo.job_state_updates == 0
    parent = repo.get_job(created.job.job_id)
    assert parent is not None
    assert parent.state == "queued"

    progress = service.get_job_progress(created.job.job_id)

    assert progress.state == "completed"
    assert repo.job_state_updates == 1


def test_complete_scan_only_bulk_uses_single_bulk_stage_update() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)
    repo.single_stage_updates = 0
    repo.multi_stage_updates = 0
    repo.bulk_stage_updates = 0
    repo.job_state_updates = 0

    updated_count = service.complete_scan_only_bulk(
        [
            (
                created.job.job_id,
                items[0].job_item_id,
                StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
            ),
            (
                created.job.job_id,
                items[1].job_item_id,
                StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-2"}),
            ),
        ]
    )

    refreshed = service.list_job_items(job_id=created.job.job_id)
    assert updated_count == 2
    assert repo.single_stage_updates == 0
    assert repo.multi_stage_updates == 0
    assert repo.bulk_stage_updates == 1
    assert repo.job_state_updates == 1
    assert all(item.state == "completed" for item in refreshed)
    assert all(item.scan_stage.state == "completed" for item in refreshed)
    assert all(item.delivery_stage.state == "skipped" for item in refreshed)
    parent = service.get_job_or_404(created.job.job_id)
    assert parent.state == "completed"
    assert parent.completed_at is not None


def test_complete_scan_only_bulk_can_defer_parent_refresh() -> None:
    repo = CountingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    items = service.list_job_items(job_id=created.job.job_id)
    repo.bulk_stage_updates = 0
    repo.job_state_updates = 0

    updated_count = service.complete_scan_only_bulk(
        [
            (
                created.job.job_id,
                items[0].job_item_id,
                StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-1"}),
            ),
            (
                created.job.job_id,
                items[1].job_item_id,
                StageUpdateRequest(state="completed", result={"verdict": "Benign", "scanGuid": "scan-2"}),
            ),
        ],
        refresh_parent=False,
    )

    assert updated_count == 2
    assert repo.bulk_stage_updates == 1
    assert repo.job_state_updates == 0
    parent = service.get_job_or_404(created.job.job_id)
    assert parent.state == "queued"

    progress = service.get_job_progress(created.job.job_id)

    assert progress.state == "completed"
    assert repo.job_state_updates == 1


def test_policy_completion_auto_requests_remediation_when_plan_present() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/bad.exe",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Malicious"}),
        )
    )
    updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result=PolicyDecision(
                    remediation_plan={"action": "quarantine"},
                    delivery_target={"connector": "sharepoint"},
                ).model_dump(mode="json"),
            ),
        )
    )

    assert updated.state == "queued"
    assert bus.snapshot()[-1].message_type == "remediation_requested"
    assert bus.snapshot()[-1].payload["remediation_plan"]["action"] == "quarantine"


def test_policy_completion_auto_requests_delivery_when_no_remediation_plan() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Benign"}),
        )
    )
    updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result=PolicyDecision(
                    delivery_target={"connector": "sharepoint"},
                ).model_dump(mode="json"),
            ),
        )
    )

    assert updated.state == "deliver_pending"
    assert updated.remediation_stage.state == "skipped"
    assert updated.remediation_stage.result == {"reason": "benign_verdict"}
    assert updated.dianna_stage.state == "skipped"
    assert updated.dianna_stage.result == {"reason": "not_auto_requested", "details": {"verdict": "Benign"}}
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"


def test_policy_completion_marks_malicious_no_remediation_as_not_configured() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/bad.exe",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]

    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Malicious"}),
        )
    )
    updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result=PolicyDecision(
                    delivery_target={"connector": "sharepoint"},
                ).model_dump(mode="json"),
            ),
        )
    )

    assert updated.state == "deliver_pending"
    assert updated.remediation_stage.state == "skipped"
    assert updated.remediation_stage.result == {"reason": "remediation_not_configured"}
    assert updated.dianna_stage.state == "skipped"
    assert updated.dianna_stage.result == {"reason": "not_auto_requested", "details": {"verdict": "Malicious"}}
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"


def test_request_result_delivery_waits_on_dianna_when_required() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="completed", result={"verdict": "Malicious"}))
    service.update_remediation_stage(item.job_item_id, StageUpdateRequest(state="skipped"))
    asyncio.run(
        service.request_dianna_analysis(
            item.job_item_id,
            DiannaAnalysisRequest(reason="auto_on_malicious", wait_for_delivery=True),
        )
    )
    refreshed = repo.get_job_item(item.job_item_id)
    assert refreshed is not None
    assert refreshed.delivery_requirements.wait_for_dianna is True

    try:
        asyncio.run(
            service.request_result_delivery(
                item.job_item_id,
                DeliveryRequest(delivery_target={"connector": "sharepoint"}),
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "delivery_waiting_on_dianna"
    else:
        raise AssertionError("expected delivery to wait on DIANNA")


def test_request_result_delivery_proceeds_after_dianna_terminal() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="completed", result={"verdict": "Malicious"}))
    service.update_remediation_stage(item.job_item_id, StageUpdateRequest(state="skipped"))
    asyncio.run(
        service.request_dianna_analysis(
            item.job_item_id,
            DiannaAnalysisRequest(reason="auto_on_malicious", wait_for_delivery=True),
        )
    )
    service.update_dianna_stage(item.job_item_id, StageUpdateRequest(state="completed", result={"analysisId": "d1"}))

    updated = asyncio.run(
        service.request_result_delivery(
            item.job_item_id,
            DeliveryRequest(delivery_target={"connector": "sharepoint"}),
        )
    )

    assert updated.state == "deliver_pending"
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"
    assert bus.snapshot()[-1].payload["final_result"]["dianna"]["analysisId"] == "d1"


def test_request_result_delivery_does_not_wait_on_dianna_by_default() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}])
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    service.update_scan_stage(item.job_item_id, StageUpdateRequest(state="completed", result={"verdict": "Malicious"}))
    service.update_remediation_stage(item.job_item_id, StageUpdateRequest(state="skipped"))
    asyncio.run(
        service.request_dianna_analysis(
            item.job_item_id,
            DiannaAnalysisRequest(reason="auto_on_malicious"),
        )
    )

    updated = asyncio.run(
        service.request_result_delivery(
            item.job_item_id,
            DeliveryRequest(delivery_target={"connector": "sharepoint"}),
        )
    )

    assert updated.state == "deliver_pending"
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"


def test_policy_completion_can_request_dianna_and_wait_for_delivery() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {
                        "object_identity": "/finance/bad.exe",
                        "payload": {},
                    }
                ]
            )
        )
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    asyncio.run(
        service.advance_scan_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"verdict": "Malicious"}),
        )
    )
    policy_updated = asyncio.run(
        service.advance_policy_stage(
            item.job_item_id,
            StageUpdateRequest(
                state="completed",
                result=PolicyDecision(
                    delivery_target={"connector": "sharepoint"},
                    request_dianna=True,
                    wait_for_dianna_before_delivery=True,
                ).model_dump(mode="json"),
            ),
        )
    )
    assert policy_updated.delivery_requirements.wait_for_dianna is True
    assert bus.snapshot()[-1].message_type == "dianna_analysis_requested"

    updated = asyncio.run(
        service.advance_dianna_stage(
            item.job_item_id,
            StageUpdateRequest(state="completed", result={"analysisId": "d2"}),
        )
    )

    assert updated.state == "deliver_pending"
    assert bus.snapshot()[-1].message_type == "result_sink_emit_requested"
    assert bus.snapshot()[-1].payload["final_result"]["dianna"]["analysisId"] == "d2"
