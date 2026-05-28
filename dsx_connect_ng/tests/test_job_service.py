import asyncio

from fastapi import HTTPException

from dsx_connect_ng.config import RecoverySettings
from dsx_connect_ng.control_plane.models import IntegrationCreate, ProtectedScopeCreate
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.jobs.bus import InMemoryJobBus, JobBus
from dsx_connect_ng.jobs.contracts import MessageEnvelope

from dsx_connect_ng.jobs.models import BatchJobSubmitRequest, DeliveryRequest, DiannaAnalysisRequest, JobCreate, JobSubmitRequest, PolicyDecision, RemediationRequest, StageUpdateRequest
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService


class FailingJobBus(JobBus):
    async def publish(self, job) -> None:
        raise RuntimeError("broker down")

    async def status(self) -> dict:
        return {"backend": "failing"}


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
                        "scan_targets": [{"connector": "scan-sharepoint"}],
                        "workflow_summary_targets": [],
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
    assert updated.delivery_stage.result == {"reason": "workflow_summary_not_requested"}
    assert updated.state == "completed"


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
