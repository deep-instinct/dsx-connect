import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from dsx_connect_ng.control_plane.models import IntegrationCreate, ProtectedScopeCreate
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.bus import InMemoryJobBus
from dsx_connect_ng.jobs.contracts import MessageEnvelope, PolicyEvaluationRequested, ResultSinkEmitRequested, ScanItemRequested
from dsx_connect_ng.jobs.models import (
    BatchJobSubmitRequest,
    ContentPreservationDecision,
    ContentSource,
    DeliveryDispatchDecision,
    DeliveryResult,
    DeliveryRequirements,
    DiannaResult,
    PolicyHandoffDecision,
    PolicyHandoffRequest,
    PolicyStageResult,
    RemediationResult,
    ScanResult,
    StageApplicabilityDecision,
    StageResultDeliveryPolicy,
)
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.readers.proxy import ConnectorProxyReader, build_connector_proxy_reader, local_stub_connector_read, resolve_connector_proxy_runtime_config
from dsx_connect_ng.readers.resolver import build_scan_reader, resolve_reader_strategy
from dsx_connect_ng.workers.delivery_worker import process_result_sink_message
from dsx_connect_ng.workers.dianna_worker import process_dianna_message
from dsx_connect_ng.workers.policy_worker import process_policy_message
from dsx_connect_ng.workers.policy_engine import stub_policy_engine
from dsx_connect_ng.workers.connector_actions import build_legacy_connector_action_payload
from dsx_connect_ng.workers.connector_actions import normalize_connector_remediation_response
from dsx_connect_ng.workers.remediation_worker import build_remediation_executor, process_remediation_message
from dsx_connect_ng.workers import scan_worker as scan_worker_module
from dsx_connect_ng.workers.scan_worker import (
    ScanOnlyBatchCoordinator,
    TerminalScanError,
    execute_scan_via_dsxa,
    mark_scan_message_failed_after_retries,
    map_dsxa_scan_response,
    process_scan_message,
    resolve_local_scan_path,
)


class CountingRuntimeJobRepository(InMemoryJobRepository):
    def __init__(self) -> None:
        super().__init__()
        self.runtime_starts = 0
        self.runtime_clears = 0

    def mark_scan_runtime_started(self, *, job_id: str, job_item_id: str) -> None:
        self.runtime_starts += 1
        super().mark_scan_runtime_started(job_id=job_id, job_item_id=job_item_id)

    def clear_scan_runtime(self, *, job_item_id: str) -> None:
        self.runtime_clears += 1
        super().clear_scan_runtime(job_item_id=job_item_id)


class ReadFailingJobRepository(InMemoryJobRepository):
    def get_job_item(self, job_item_id: str):
        raise AssertionError(f"unexpected job item read: {job_item_id}")

    def get_job(self, job_id: str):
        raise AssertionError(f"unexpected job read: {job_id}")


@pytest.fixture(autouse=True)
def reset_scan_worker_dsxa_client_cache():
    scan_worker_module._DSXA_CLIENT = None
    scan_worker_module._DSXA_CLIENT_KEY = None
    previous_scope = scan_worker_module._SCANNER_CLIENT_SCOPE
    previous_transport = scan_worker_module.settings.scanner.transport
    scan_worker_module._SCANNER_CLIENT_SCOPE = "shared"
    scan_worker_module.settings.scanner.transport = "binary_stream"
    yield
    scan_worker_module._DSXA_CLIENT = None
    scan_worker_module._DSXA_CLIENT_KEY = None
    scan_worker_module._SCANNER_CLIENT_SCOPE = previous_scope
    scan_worker_module.settings.scanner.transport = previous_transport


async def _fake_scan(_request, _reader) -> ScanResult:
    return ScanResult(
        verdict="Malicious",
        scanGuid="scan-worker-1",
        fileType="PE32FileType",
        scanDurationUs=1000,
    )


async def _fake_benign_scan(_request, _reader) -> ScanResult:
    return ScanResult(
        verdict="Benign",
        scanGuid="scan-worker-benign-1",
        fileType="TextFileType",
        scanDurationUs=1000,
    )


async def _fake_retryable_scan_failure(_request, _reader) -> ScanResult:
    raise RuntimeError("scanner_transport_failure: All connection attempts failed")


async def _fake_policy_engine(_request) -> PolicyHandoffDecision:
    return PolicyHandoffDecision(
        policy_stage_result=PolicyStageResult(policy_id="policy-1"),
        remediation=StageApplicabilityDecision(state="requested", details={"remediation_plan": {"action": "quarantine"}}),
        dianna=StageApplicabilityDecision(state="requested"),
        delivery=DeliveryDispatchDecision(
            request_now=False,
            wait_for_dianna=True,
            targets=[{"connector": "sharepoint"}],
        ),
        content_preservation=ContentPreservationDecision(mode="none", reason="not_needed"),
        result_delivery_policy=StageResultDeliveryPolicy(
            scan="malicious_only",
            remediation="all_outcomes",
            dianna="completed_only",
        ),
    )


async def _fake_policy_engine_without_dianna(_request) -> PolicyHandoffDecision:
    return PolicyHandoffDecision(
        policy_stage_result=PolicyStageResult(policy_id="policy-1"),
        remediation=StageApplicabilityDecision(state="requested", details={"remediation_plan": {"action": "quarantine"}}),
        dianna=StageApplicabilityDecision(state="skipped", reason="not_auto_requested", details={"verdict": "Malicious"}),
        delivery=DeliveryDispatchDecision(
            request_now=False,
            wait_for_dianna=False,
            targets=[{"connector": "sharepoint"}],
        ),
        content_preservation=ContentPreservationDecision(mode="none", reason="not_needed"),
        result_delivery_policy=StageResultDeliveryPolicy(
            scan="malicious_only",
            remediation="all_outcomes",
            dianna="completed_only",
        ),
    )


async def _fake_remediation(_request) -> RemediationResult:
    return RemediationResult(
        action="quarantine",
        outcome="succeeded",
        targetPath="/quarantine/bad.exe",
    )


def test_stub_policy_engine_uses_resolved_policy_context() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        scope_id="scope-1",
        object_identity="/finance/bad.exe",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="Malicious", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "policy_id": "scope-policy-1",
                "auto_dianna_on_verdicts": ["malicious"],
                "wait_for_dianna_on_auto_request": True,
                "malicious_verdict": {
                    "action": "quarantine",
                    "quarantine_target": {"prefix": "tenant-quarantine"},
                    "tag_on_quarantine": True,
                },
                "non_compliant_treatment": "treat_as_malicious",
                "not_scanned_treatment": "treat_as_benign",
                "remediation_plan_by_verdict": {
                    "malicious": {"action": "quarantine"},
                },
                "result_delivery_policy": {
                    "scan": "malicious_only",
                    "remediation": "all_outcomes",
                    "dianna": "completed_only",
                },
                "delivery": {
                    "scan_targets": [{"connector": "scan-sink"}],
                    "workflow_summary_targets": [{"connector": "summary-sink"}],
                },
                "content_preservation_mode_by_verdict": {
                    "malicious": "cached",
                },
            }
        },
    )
    decision = asyncio.run(stub_policy_engine(request))

    assert decision.policy_stage_result.policy_id == "scope-policy-1"
    assert decision.remediation.state == "requested"
    assert decision.remediation.details["remediation_plan"]["action"] == "quarantine"
    assert decision.dianna.state == "requested"
    assert decision.delivery.wait_for_dianna is True
    assert decision.delivery.scan_targets == [{"connector": "scan-sink"}]
    assert decision.delivery.workflow_summary_targets == [{"connector": "summary-sink"}]
    assert decision.content_preservation.mode == "cached"
    assert decision.result_delivery_policy.scan == "malicious_only"


def test_stub_policy_engine_preserves_empty_workflow_summary_targets() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="Benign", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "result_delivery_policy": {
                    "scan": "all_results",
                    "remediation": "all_outcomes",
                    "dianna": "completed_only",
                },
                "delivery": {
                    "scan_targets": [{"connector": "scan-sink"}],
                    "workflow_summary_targets": [],
                },
            }
        },
    )
    decision = asyncio.run(stub_policy_engine(request))

    assert decision.delivery.scan_targets == [{"connector": "scan-sink"}]
    assert decision.delivery.workflow_summary_targets == []
    assert decision.delivery.targets == []
    assert decision.delivery.scan_targets_configured is True
    assert decision.delivery.workflow_summary_targets_configured is True
    assert decision.delivery.request_now is False


def test_stub_policy_engine_maps_non_compliant_to_malicious_policy() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/risky.bin",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="Non-Compliant", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "policy_id": "scope-policy-1",
                "auto_dianna_on_verdicts": ["malicious"],
                "wait_for_dianna_on_auto_request": True,
                "malicious_verdict": {
                    "action": "delete",
                },
                "non_compliant_treatment": "treat_as_malicious",
            }
        },
    )

    decision = asyncio.run(stub_policy_engine(request))

    assert decision.remediation.state == "requested"
    assert decision.remediation.details["remediation_plan"]["action"] == "delete"
    assert decision.dianna.state == "requested"
    assert decision.policy_stage_result.decision_trace["effective_verdict"] == "malicious"
    assert decision.remediation.details["remediation_plan"]["action"] == "delete"


def test_stub_policy_engine_maps_not_scanned_to_benign_policy() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/unknown.bin",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="not scanned", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "policy_id": "scope-policy-1",
                "malicious_verdict": {
                    "action": "delete",
                },
                "not_scanned_treatment": "treat_as_benign",
            }
        },
    )

    decision = asyncio.run(stub_policy_engine(request))

    assert decision.remediation.state == "skipped"
    assert decision.remediation.reason == "benign_verdict"
    assert decision.dianna.state == "skipped"
    assert decision.policy_stage_result.decision_trace["effective_verdict"] == "benign"


def test_stub_policy_engine_builds_tag_only_remediation_plan() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/tag-me.bin",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="Malicious", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "policy_id": "scope-policy-1",
                "malicious_verdict": {
                    "action": "tag_only",
                },
            }
        },
    )

    decision = asyncio.run(stub_policy_engine(request))

    assert decision.remediation.state == "requested"
    assert decision.remediation.details["remediation_plan"] == {"action": "tag_only", "tag": True}


def test_stub_policy_engine_quarantine_defaults_to_tagging() -> None:
    request = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/quarantine.bin",
        content_source=ContentSource(mode="original"),
        delivery_requirements=DeliveryRequirements(wait_for_dianna=False),
        scan_result=ScanResult(verdict="Malicious", scanGuid="scan-1"),
        item_payload={},
        policy_context={
            "resolved_policy": {
                "policy_id": "scope-policy-1",
                "malicious_verdict": {
                    "action": "quarantine",
                    "quarantine_target": {
                        "prefix": "tenant-quarantine",
                        "collision_strategy": "suffix_random",
                        "suffix_length": 10,
                    },
                },
            }
        },
    )

    decision = asyncio.run(stub_policy_engine(request))

    assert decision.remediation.state == "requested"
    assert decision.remediation.details["remediation_plan"]["action"] == "quarantine"
    assert decision.remediation.details["remediation_plan"]["tag"] is True
    assert decision.remediation.details["remediation_plan"]["quarantineTarget"]["collision_strategy"] == "suffix_random"
    assert decision.remediation.details["remediation_plan"]["quarantineTarget"]["suffix_length"] == 10



async def _fake_delivery(_request) -> DeliveryResult:
    return DeliveryResult(
        destination="sharepoint",
        outcome="delivered",
        externalReference="delivery-ref-1",
    )


async def _fake_dianna(_request) -> DiannaResult:
    return DiannaResult(
        analysisId="analysis-1",
        status="completed",
    )


def test_scan_worker_processes_message_and_enqueues_policy_evaluation() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.message_type == "scan_item_requested"

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.scan_stage.result is not None
    assert item.scan_stage.result["scan_guid"] == "scan-worker-1"
    assert item.scan_stage.metadata == {}
    assert item.policy_stage.state == "pending"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "policy_evaluation_requested" in published_types
    assert "dianna_analysis_requested" not in published_types
    assert "remediation_requested" not in published_types


def test_scan_worker_scan_only_completes_without_policy_evaluation() -> None:
    repo = CountingRuntimeJobRepository()
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
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.message_type == "scan_item_requested"

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"
    assert item.scan_stage.result is not None
    assert item.scan_stage.result["scan_guid"] == "scan-worker-1"
    assert item.scan_stage.started_at is None
    assert item.policy_stage.state == "skipped"
    assert item.policy_stage.result == {"reason": "scan_only"}
    assert item.remediation_stage.state == "skipped"
    assert item.delivery_stage.state == "skipped"
    assert item.dianna_stage.state == "skipped"
    assert repo.runtime_starts == 1
    assert repo.runtime_clears == 1
    assert repo.count_active_scan_runtime(created.job.job_id) == 0
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "policy_evaluation_requested" not in published_types


def test_scan_worker_scan_only_can_skip_runtime_leases() -> None:
    repo = CountingRuntimeJobRepository()
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
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.message_type == "scan_item_requested"

    asyncio.run(
        process_scan_message(
            service,
            first_message,
            execute_scan=_fake_scan,
            scan_only_runtime_leases=False,
        )
    )

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"
    assert item.scan_stage.result is not None
    assert item.scan_stage.result["scan_guid"] == "scan-worker-1"
    assert repo.runtime_starts == 0
    assert repo.runtime_clears == 0
    assert repo.count_active_scan_runtime(created.job.job_id) == 0


def test_scan_worker_scan_only_can_thread_service_io() -> None:
    repo = CountingRuntimeJobRepository()
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
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.message_type == "scan_item_requested"

    asyncio.run(
        process_scan_message(
            service,
            first_message,
            execute_scan=_fake_scan,
            service_io_threaded=True,
        )
    )

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"
    assert item.scan_stage.result is not None
    assert item.scan_stage.result["scan_guid"] == "scan-worker-1"
    assert repo.runtime_starts == 1
    assert repo.runtime_clears == 1


def test_scan_only_batch_coordinator_runs_scans_concurrently() -> None:
    repo = CountingRuntimeJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/b.pdf", "payload": {"scanOnly": True}},
                    {"object_identity": "/finance/c.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    messages = bus.snapshot()[:3]
    assert all(isinstance(message, MessageEnvelope) for message in messages)
    active = 0
    max_active = 0

    async def fake_scan(request, _reader) -> ScanResult:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ScanResult(
            verdict="Benign",
            scanGuid=f"scan-{request.job_item_id}",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=fake_scan,
            batch_size=3,
            max_wait_seconds=1.0,
            scan_concurrency=3,
            scan_only_runtime_leases=False,
            service_io_threaded=False,
        )
        await asyncio.gather(*(coordinator.add(message) for message in messages if isinstance(message, MessageEnvelope)))

    asyncio.run(run_batch())

    items = service.list_job_items(job_id=created.job.job_id)
    assert [item.state for item in items] == ["completed", "completed", "completed"]
    assert max_active == 3
    assert repo.runtime_starts == 0
    assert repo.runtime_clears == 0


def test_scan_only_batch_coordinator_can_ack_after_pool_acceptance() -> None:
    repo = CountingRuntimeJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    message = bus.snapshot()[0]
    assert isinstance(message, MessageEnvelope)
    scan_started = asyncio.Event()
    finish_scan = asyncio.Event()

    async def fake_scan(request, _reader) -> ScanResult:
        scan_started.set()
        await finish_scan.wait()
        return ScanResult(
            verdict="Benign",
            scanGuid=f"scan-{request.job_item_id}",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=fake_scan,
            batch_size=1,
            max_wait_seconds=1.0,
            scan_concurrency=1,
            scan_only_runtime_leases=False,
            service_io_threaded=False,
            ack_mode="accepted",
        )
        await coordinator.add(message)
        assert service.list_job_items(job_id=created.job.job_id)[0].state != "completed"
        await asyncio.wait_for(scan_started.wait(), timeout=1.0)
        finish_scan.set()
        await coordinator.flush_all()

    asyncio.run(run_batch())

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"


def test_scan_only_batch_coordinator_can_ack_after_scan_buffering() -> None:
    repo = CountingRuntimeJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/a.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    message = bus.snapshot()[0]
    assert isinstance(message, MessageEnvelope)
    scan_finished = asyncio.Event()

    async def fake_scan(request, _reader) -> ScanResult:
        scan_finished.set()
        return ScanResult(
            verdict="Benign",
            scanGuid=f"scan-{request.job_item_id}",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=fake_scan,
            batch_size=100,
            max_wait_seconds=60.0,
            scan_concurrency=1,
            scan_only_runtime_leases=False,
            service_io_threaded=False,
            ack_mode="scanned",
        )
        await coordinator.add(message)
        assert scan_finished.is_set()
        assert service.list_job_items(job_id=created.job.job_id)[0].state != "completed"
        await coordinator.flush_all()

    asyncio.run(run_batch())

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"


def test_scan_only_batch_coordinator_coalesces_completion_flushes_while_write_in_flight() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    requests = [
        ScanItemRequested(
            job_id="job-1",
            job_item_id=f"item-{index}",
            integration_id="filesystem-local",
            object_identity=f"/finance/{index}.pdf",
            scan_options={"scanOnly": True, "readerStrategy": "native", "path": f"/finance/{index}.pdf"},
        )
        for index in range(6)
    ]
    flush_active = 0
    max_flush_active = 0
    flush_sizes: list[int] = []

    async def fake_scan(request, _reader) -> ScanResult:
        await asyncio.sleep(0)
        return ScanResult(
            verdict="Benign",
            scanGuid=f"scan-{request.job_item_id}",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    def fake_complete_scan_only_bulk(updates, *, refresh_parent=True):
        nonlocal flush_active, max_flush_active
        assert refresh_parent is False
        flush_active += 1
        max_flush_active = max(max_flush_active, flush_active)
        time.sleep(0.05)
        flush_sizes.append(len(updates))
        flush_active -= 1
        return len(updates)

    service.complete_scan_only_bulk = fake_complete_scan_only_bulk  # type: ignore[method-assign]

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=fake_scan,
            batch_size=2,
            max_wait_seconds=0.01,
            scan_concurrency=6,
            scan_only_runtime_leases=False,
            service_io_threaded=True,
            ack_mode="scanned",
            trust_items=True,
        )
        await asyncio.gather(*(coordinator.add(request.as_envelope()) for request in requests))
        await coordinator.flush_all()

    asyncio.run(run_batch())

    assert max_flush_active == 1
    assert sum(flush_sizes) == 6
    assert any(size > 2 for size in flush_sizes)


def test_scan_only_batch_coordinator_can_trust_claimed_items() -> None:
    repo = ReadFailingJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        object_identity="/finance/a.pdf",
        scan_options={"scanOnly": True, "readerStrategy": "native", "path": "/finance/a.pdf"},
    )

    async def fake_scan(_request, _reader) -> ScanResult:
        return ScanResult(
            verdict="Benign",
            scanGuid="scan-item-1",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    completed_updates = []

    def fake_complete_scan_only_bulk(updates, *, refresh_parent=True):
        assert refresh_parent is False
        completed_updates.extend(updates)
        return len(updates)

    service.complete_scan_only_bulk = fake_complete_scan_only_bulk  # type: ignore[method-assign]

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=fake_scan,
            batch_size=1,
            max_wait_seconds=1.0,
            scan_concurrency=1,
            scan_only_runtime_leases=False,
            service_io_threaded=False,
            trust_items=True,
        )
        await coordinator.add(request.as_envelope())
        await coordinator.flush_all()

    asyncio.run(run_batch())

    assert len(completed_updates) == 1
    assert completed_updates[0][0] == "job-1"
    assert completed_updates[0][1] == "item-1"


def test_scan_only_batch_coordinator_trusted_items_complete_after_cancel_during_scan() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/cancel-during-trusted-batch.pdf", "payload": {"scanOnly": True}},
                ]
            )
        )
    )
    message = bus.snapshot()[0]
    assert isinstance(message, MessageEnvelope)

    async def cancel_then_return_result(request, _reader) -> ScanResult:
        service.cancel_job(request.job_id)
        return ScanResult(
            verdict="Benign",
            scanGuid="scan-after-trusted-batch-cancel",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    async def run_batch() -> None:
        coordinator = ScanOnlyBatchCoordinator(
            service,
            execute_scan=cancel_then_return_result,
            batch_size=1,
            max_wait_seconds=1.0,
            scan_concurrency=1,
            scan_only_runtime_leases=False,
            service_io_threaded=False,
            trust_items=True,
        )
        await coordinator.add(message)
        await coordinator.flush_all()

    asyncio.run(run_batch())

    item = service.list_job_items(job_id=created.job.job_id)[0]
    job = service.get_job_or_404(created.job.job_id)
    assert job.state == "cancelled"
    assert item.state == "completed"
    assert item.scan_stage.state == "completed"
    assert item.scan_stage.result["scan_guid"] == "scan-after-trusted-batch-cancel"


def test_scan_worker_clears_runtime_lease_after_terminal_scan_failure() -> None:
    repo = CountingRuntimeJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/a.pdf"}]))
    )
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)

    async def fail_terminal(_request, _reader):
        raise TerminalScanError("bad_file", "cannot scan")

    asyncio.run(process_scan_message(service, first_message, execute_scan=fail_terminal))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "failed"
    assert repo.runtime_starts == 1
    assert repo.runtime_clears == 1
    assert repo.count_active_scan_runtime(created.job.job_id) == 0


def test_scan_worker_scan_only_item_recovery_keeps_running_transition() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                recovery_mode="item",
                items=[
                    {
                        "object_identity": "/finance/a.pdf",
                        "payload": {"scanOnly": True},
                    }
                ],
            )
        )
    )
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.payload["scan_options"]["effectiveRecoveryMode"] == "item"

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "completed"
    assert item.scan_stage.started_at is not None
    assert item.policy_stage.state == "skipped"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "policy_evaluation_requested" not in published_types


def test_scan_worker_skips_cancelled_item() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/cancelled.exe"}]))
    )
    first_message = bus.snapshot()[0]
    service.cancel_job(created.job.job_id)

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert item.state == "cancelled"
    assert item.scan_stage.state == "pending"
    assert published_types == ["scan_item_requested"]


def test_scan_worker_caches_cancelled_parent_job(monkeypatch) -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                items=[
                    {"object_identity": "/finance/cancelled-a.exe"},
                    {"object_identity": "/finance/cancelled-b.exe"},
                ]
            )
        )
    )
    first_message, second_message = bus.snapshot()
    service.cancel_job(created.job.job_id)

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))

    def fail_item_lookup(_job_item_id):
        raise AssertionError("cancelled parent job should skip before item lookup")

    monkeypatch.setattr(service, "get_job_item_or_404", fail_item_lookup)
    asyncio.run(process_scan_message(service, second_message, execute_scan=_fake_scan))


def test_scan_worker_discards_completion_when_job_cancelled_during_scan() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/cancel-during-scan.exe"}]))
    )
    first_message = bus.snapshot()[0]

    async def cancel_then_return_result(_request, _reader) -> ScanResult:
        service.cancel_job(created.job.job_id)
        return ScanResult(
            verdict="Benign",
            scanGuid="scan-after-cancel",
            fileType="TextFileType",
            scanDurationUs=1000,
        )

    asyncio.run(process_scan_message(service, first_message, execute_scan=cancel_then_return_result))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert item.state == "cancelled"
    assert item.scan_stage.state == "running"
    assert published_types == ["scan_item_requested"]


def test_scan_worker_handoff_includes_resolved_policy_context_from_control_plane() -> None:
    control_plane = ControlPlaneService(repo=InMemoryControlPlaneRepository())
    integration = control_plane.create_integration(
        IntegrationCreate(
            integration_id="filesystem-local",
            platform="filesystem",
            platform_key="local-fs",
            display_name="Filesystem",
            config={
                "policy": {
                    "policy_id": "integration-policy",
                    "auto_dianna_on_verdicts": ["malicious"],
                    "delivery": {
                        "workflow_summary_targets": [{"connector": "integration-summary"}],
                    },
                }
            },
        )
    )
    scope = control_plane.create_scope(
        ProtectedScopeCreate(
            scope_id="scope-1",
            integration_id=integration.integration_id,
            scope_type="path",
            resource_selector="/finance",
            display_name="Finance",
            mode="monitor",
            post_scan_policy={
                "policy_id": "scope-policy",
                "delivery": {
                    "scan_targets": [{"connector": "scope-scan"}],
                },
            },
        )
    )
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus, control_plane=control_plane)
    created = asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                integration_id=integration.integration_id,
                scope_id=scope.scope_id,
                items=[{"object_identity": "/finance/bad.exe"}],
            )
        )
    )
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )
    request = PolicyEvaluationRequested.from_envelope(policy_message)

    assert request.policy_context["integration_config"]["policy"]["policy_id"] == "integration-policy"
    assert request.policy_context["scope_policy"]["policy_id"] == "scope-policy"
    assert request.policy_context["resolved_policy"]["policy_id"] == "scope-policy"
    assert request.policy_context["resolved_policy"]["delivery"]["scan_targets"] == [{"connector": "scope-scan"}]
    assert request.item_metadata["integration"]["integration_id"] == integration.integration_id
    assert request.item_metadata["scope"]["scope_id"] == scope.scope_id


def test_policy_worker_processes_message_and_requests_follow_on_work() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )

    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=_fake_policy_engine))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.policy_stage.result is not None
    assert item.policy_stage.result["dianna"]["state"] == "requested"
    assert item.delivery_requirements.wait_for_dianna is True
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "dianna_analysis_requested" in published_types
    assert "remediation_requested" in published_types


def test_remediation_worker_processes_message_and_requests_delivery() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )
    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=_fake_policy_engine_without_dianna))

    remediation_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "remediation_requested"
    )
    asyncio.run(process_remediation_message(service, remediation_message, execute_remediation=_fake_remediation))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.remediation_stage.result is not None
    assert item.remediation_stage.result["action"] == "quarantine"
    assert item.remediation_stage.result["targetPath"] == "/quarantine/bad.exe"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "result_sink_emit_requested" in published_types


def test_stub_remediation_executor_reports_tag_only() -> None:
    from dsx_connect_ng.jobs.contracts import RemediationRequested
    from dsx_connect_ng.workers.remediation_worker import stub_remediation_executor

    request = RemediationRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/tag-me.bin",
        remediation_plan={"action": "tag_only", "tag": True},
        scan_result={"verdict": "Malicious"},
    )

    result = asyncio.run(stub_remediation_executor(request))

    assert result.action == "tag_only"
    assert result.target_path is None
    assert result.details["tagApplied"] is True


def test_build_legacy_connector_action_payload_uses_connector_action_override() -> None:
    from dsx_connect_ng.jobs.contracts import RemediationRequested

    request = RemediationRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        scope_id="scope-1",
        object_identity="/finance/bad.exe",
        content_source={"mode": "original", "locator": "/finance/bad.exe"},
        scan_result={"verdict": "Malicious"},
        remediation_plan={
            "action": "quarantine",
            "targetPath": "tenant-quarantine",
            "tag": True,
        },
    )

    payload = build_legacy_connector_action_payload(
        request,
        connector_action=request.as_connector_action_request(),
        connector_url="http://127.0.0.1:8620/filesystem",
    )

    assert payload["location"] == "/finance/bad.exe"
    assert payload["connector_url"] == "http://127.0.0.1:8620/filesystem"
    assert payload["item_action"] == "movetag"
    assert payload["item_action_move_metainfo"] == "tenant-quarantine"
    assert payload["connector"]["item_action"] == "movetag"
    assert payload["tags"] == {"Verdict": "Malicious"}
    assert payload["requested_action"]["type"] == "movetag"
    assert payload["requested_action"]["destination"]["filename"] == "bad.exe_item1"
    assert payload["scan_context"]["verdict"] == "Malicious"
    assert payload["job_item_id"] == "item-1"


def test_normalize_connector_remediation_response_maps_legacy_payload() -> None:
    response = normalize_connector_remediation_response(
        {"status": "completed", "action": "move", "path": "/quarantine/bad.exe"},
        fallback_action="move",
    )

    assert response.status == "success"
    assert response.applied_action == "move"
    assert response.target_path == "/quarantine/bad.exe"


def test_build_remediation_executor_falls_back_to_stub_when_connector_action_fails(monkeypatch) -> None:
    from dsx_connect_ng.jobs.contracts import RemediationRequested

    control_plane = ControlPlaneService(repo=InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="integration-1",
            platform="filesystem",
            platform_key="local-fs",
            display_name="Filesystem",
            config={
                "reader": {
                    "proxy": {
                        "base_url": "http://127.0.0.1:8620",
                        "connector_name": "filesystem",
                    }
                }
            },
        )
    )
    service = JobService(repo=InMemoryJobRepository(), bus=InMemoryJobBus(), control_plane=control_plane)

    async def fail_connector_action(*_args, **_kwargs):
        raise RuntimeError("connector unavailable")

    monkeypatch.setattr("dsx_connect_ng.workers.remediation_worker.execute_connector_item_action", fail_connector_action)

    request = RemediationRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        object_identity="/finance/bad.exe",
        scan_result={"verdict": "Malicious"},
        remediation_plan={"action": "delete"},
    )

    result = asyncio.run(build_remediation_executor(service)(request))

    assert result.action == "delete"
    assert result.details["worker"] == "remediation_stub"


def test_build_remediation_executor_rejects_unsupported_connector_action() -> None:
    from dsx_connect_ng.jobs.contracts import RemediationRequested

    control_plane = ControlPlaneService(repo=InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="integration-1",
            platform="filesystem",
            platform_key="local-fs",
            display_name="Filesystem",
            capability_remediate=True,
            config={
                "reader": {
                    "proxy": {
                        "base_url": "http://127.0.0.1:8620",
                        "connector_name": "filesystem",
                    }
                },
                "remediation": {
                    "supports_delete": False,
                    "supports_move": True,
                    "supports_tag": False,
                    "supports_movetag": False,
                },
            },
        )
    )
    service = JobService(repo=InMemoryJobRepository(), bus=InMemoryJobBus(), control_plane=control_plane)

    request = RemediationRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        object_identity="/finance/bad.exe",
        scan_result={"verdict": "Malicious"},
        remediation_plan={"action": "delete"},
    )

    executor = build_remediation_executor(service)

    try:
        asyncio.run(executor(request))
    except TerminalScanError as exc:
        assert exc.code == "connector_action_not_supported"
    else:
        raise AssertionError("expected TerminalScanError")


def test_result_sink_worker_processes_message_and_completes_item() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )
    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=_fake_policy_engine_without_dianna))
    remediation_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "remediation_requested"
    )
    asyncio.run(process_remediation_message(service, remediation_message, execute_remediation=_fake_remediation))
    delivery_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "result_sink_emit_requested"
    )

    asyncio.run(process_result_sink_message(service, delivery_message, execute_result_sink=_fake_delivery))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.delivery_stage.result is not None
    assert item.delivery_stage.result["destination"] == "sharepoint"
    assert item.delivery_stage.result["externalReference"] == "delivery-ref-1"
    assert item.state == "completed"
    parent = service.get_batch_job_or_404(created.job.job_id)
    assert parent.job.state == "completed"


def test_result_sink_worker_handles_stage_result_delivery_without_advancing_delivery_stage() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/a.pdf"}]))
    )
    item = service.list_job_items(job_id=created.job.job_id)[0]
    request = ResultSinkEmitRequested(
        job_id=created.job.job_id,
        job_item_id=item.job_item_id,
        object_identity=item.object_identity,
        result_type="scan_result",
        result_payload={"verdict": "Benign"},
        delivery_target={"delivery_target": {"connector": "sharepoint"}},
    ).as_envelope()

    asyncio.run(process_result_sink_message(service, request, execute_result_sink=_fake_delivery))

    refreshed = service.get_job_item_or_404(item.job_item_id)
    assert refreshed.delivery_stage.state == "pending"
    assert refreshed.state == "queued"


def test_result_sink_worker_completes_item_without_remediation_when_policy_goes_straight_to_delivery() -> None:
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
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_benign_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )
    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=stub_policy_engine))
    delivery_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "result_sink_emit_requested"
    )

    asyncio.run(process_result_sink_message(service, delivery_message, execute_result_sink=_fake_delivery))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.remediation_stage.state == "skipped"
    assert item.remediation_stage.result == {"reason": "benign_verdict"}
    assert item.dianna_stage.state == "skipped"
    assert item.dianna_stage.result == {
        "reason": "not_auto_requested",
        "details": {"verdict": "Benign", "effective_verdict": "benign"},
    }
    assert item.delivery_stage.state == "completed"
    assert item.state == "completed"


def test_dianna_worker_processes_message_and_unblocks_delivery() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan))
    policy_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "policy_evaluation_requested"
    )
    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=_fake_policy_engine))

    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "dianna_analysis_requested" in published_types
    assert "remediation_requested" in published_types
    assert "result_sink_emit_requested" not in published_types

    dianna_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "dianna_analysis_requested"
    )
    asyncio.run(process_dianna_message(service, dianna_message, execute_dianna=_fake_dianna))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.dianna_stage.result is not None
    assert item.dianna_stage.result["analysisId"] == "analysis-1"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "result_sink_emit_requested" in published_types


def test_scan_worker_marks_terminal_source_errors_failed() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/missing.exe"}]))
    )
    first_message = bus.snapshot()[0]

    async def fail_scan(_request, _reader) -> ScanResult:
        raise TerminalScanError("content_missing", "no readable file")

    asyncio.run(process_scan_message(service, first_message, execute_scan=fail_scan))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.scan_stage.state == "failed"
    assert item.scan_stage.error is not None
    assert item.scan_stage.error["code"] == "content_missing"
    assert bus.snapshot()[-1].message_type == "scan_item_requested"


def test_scan_worker_marks_exhausted_retryable_failures_failed() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    first_message = bus.snapshot()[0]

    with pytest.raises(RuntimeError):
        asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_retryable_scan_failure))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "scanning"
    assert item.scan_stage.state == "running"

    asyncio.run(
        mark_scan_message_failed_after_retries(
            service,
            first_message,
            RuntimeError("scanner_transport_failure: All connection attempts failed"),
            {"x-dsx-retry-attempt": 5},
        )
    )

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.state == "failed"
    assert item.scan_stage.state == "failed"
    assert item.scan_stage.error is not None
    assert item.scan_stage.error["reason"] == "retry_attempts_exhausted"
    assert item.scan_stage.error["retryAttempts"] == 5


def test_resolve_local_scan_path_uses_content_source_locator() -> None:
    with TemporaryDirectory() as tmpdir:
        sample = Path(tmpdir) / "sample.bin"
        sample.write_bytes(b"abc")
        request = SimpleNamespace(
            content_source=SimpleNamespace(mode="original", locator=str(sample)),
            scan_options={},
            read_hint={},
            object_identity="/finance/sample.bin",
        )

        resolved = resolve_local_scan_path(request)

        assert resolved == sample


def test_resolve_reader_strategy_prefers_request_override() -> None:
    request = SimpleNamespace(
        scan_options={"readerStrategy": "proxy"},
        read_hint={},
        integration_id=None,
    )

    assert resolve_reader_strategy(request) == "proxy"


def test_resolve_reader_strategy_uses_integration_config() -> None:
    control_plane = ControlPlaneService(InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="sharepoint-prod",
            platform="sharepoint",
            platform_key="tenant-1",
            display_name="SharePoint Prod",
            config={"reader": {"default_strategy": "proxy"}},
        )
    )
    request = SimpleNamespace(
        scan_options={},
        read_hint={},
        integration_id="sharepoint-prod",
    )

    assert resolve_reader_strategy(request, control_plane=control_plane) == "proxy"


def test_build_scan_reader_returns_connector_proxy_reader_for_proxy_strategy() -> None:
    control_plane = ControlPlaneService(InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="integration-1",
            platform="filesystem",
            platform_key="local-1",
            display_name="Filesystem",
            config={
                "reader": {
                    "proxy": {
                        "base_url": "http://connector.local",
                        "connector_name": "filesystem",
                    }
                }
            },
        )
    )
    request = SimpleNamespace(
        scan_options={"readerStrategy": "proxy"},
        read_hint={},
        integration_id="integration-1",
    )

    reader = build_scan_reader(request, control_plane=control_plane)

    assert isinstance(reader, ConnectorProxyReader)


def test_resolve_connector_proxy_runtime_config_uses_integration_config() -> None:
    control_plane = ControlPlaneService(InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="sharepoint-prod",
            platform="sharepoint",
            platform_key="tenant-1",
            display_name="SharePoint Prod",
            config={
                "reader": {
                    "default_strategy": "proxy",
                    "proxy": {
                        "base_url": "http://connector.local",
                        "connector_name": "sharepoint",
                        "auth_mode": "static_header",
                        "header_name": "X-Test-Auth",
                        "header_value": "token-1",
                    },
                }
            },
        )
    )
    request = SimpleNamespace(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="sharepoint-prod",
        scope_id=None,
        object_identity="drive:1/item:2",
        content_source=ContentSource(mode="original"),
        read_hint={},
        scan_options={},
    )

    config = resolve_connector_proxy_runtime_config(request, control_plane=control_plane)

    assert config.endpoint_url == "http://connector.local/sharepoint/read_file"
    assert config.auth_mode == "static_header"
    assert config.header_name == "X-Test-Auth"
    assert config.header_value == "token-1"


def test_build_connector_proxy_reader_uses_http_transport_config() -> None:
    control_plane = ControlPlaneService(InMemoryControlPlaneRepository())
    control_plane.create_integration(
        IntegrationCreate(
            integration_id="sharepoint-prod",
            platform="sharepoint",
            platform_key="tenant-1",
            display_name="SharePoint Prod",
            config={
                "reader": {
                    "proxy": {
                        "base_url": "http://connector.local",
                        "connector_name": "sharepoint",
                    }
                }
            },
        )
    )
    request = SimpleNamespace(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="sharepoint-prod",
        scope_id=None,
        object_identity="drive:1/item:2",
        content_source=ContentSource(mode="original"),
        read_hint={},
        scan_options={},
    )

    reader = build_connector_proxy_reader(request, control_plane=control_plane)

    assert isinstance(reader, ConnectorProxyReader)


def test_connector_proxy_reader_local_stub_resolves_local_path() -> None:
    with TemporaryDirectory() as tmpdir:
        sample = Path(tmpdir) / "sample.bin"
        sample.write_bytes(b"abc")
        request = SimpleNamespace(
            job_id="job-1",
            job_item_id="item-1",
            integration_id="integration-1",
            scope_id=None,
            object_identity="/finance/sample.bin",
            content_source=ContentSource(mode="original", locator=str(sample)),
            read_hint={},
            scan_options={},
        )

        result = asyncio.run(ConnectorProxyReader(local_stub_connector_read).acquire(request))

        assert result.local_path == sample
        assert result.details["reader"] == "connector_proxy"


def test_map_dsxa_scan_response_maps_sdk_fields() -> None:
    response = SimpleNamespace(
        scan_guid="scan-1",
        verdict=SimpleNamespace(value="Malicious"),
        verdict_details=SimpleNamespace(model_dump=lambda **kwargs: {"reason": "infected"}),
        file_info=SimpleNamespace(model_dump=lambda **kwargs: {"file_type": "PE32FileType"}, file_type="PE32FileType"),
        protected_entity=1,
        scan_duration_in_microseconds=1234,
        dsxconnect_request_elapsed_ms=10.0,
        dsxconnect_read_elapsed_ms=3.0,
        dsxconnect_dsxa_elapsed_ms=7.0,
        container_files_scanned=4,
        container_files_scanned_size=1024,
        x_custom_metadata="meta-1",
        last_update_time="now",
    )

    result = map_dsxa_scan_response(response)

    assert result.verdict == "Malicious"
    assert result.scan_guid == "scan-1"
    assert result.file_type == "PE32FileType"
    assert result.scan_duration_us == 1234
    assert result.verdict_details["reason"] == "infected"
    assert result.protected_entity == 1


def test_execute_scan_via_dsxa_enriches_scanner_metadata(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.auth_token", "token")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.timeout_seconds", 30.0)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.verify_tls", True)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.protected_entity", 1)
    captured: dict[str, object] = {}

    class FakeClient:
        instances = 0

        def __init__(self, **kwargs):
            FakeClient.instances += 1
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            captured["data"] = b"".join([chunk async for chunk in data])
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                scan_guid="scan-1",
                verdict=SimpleNamespace(value="Benign"),
                verdict_details=SimpleNamespace(model_dump=lambda **kw: {"reason": "clean"}),
                file_info=SimpleNamespace(model_dump=lambda **kw: {"file_type": "Text"}, file_type="Text"),
                protected_entity=kwargs.get("protected_entity"),
                scan_duration_in_microseconds=1234,
                dsxconnect_request_elapsed_ms=None,
                dsxconnect_read_elapsed_ms=None,
                dsxconnect_dsxa_elapsed_ms=None,
                container_files_scanned=0,
                container_files_scanned_size=0,
                x_custom_metadata=None,
                last_update_time=None,
            )

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )
    sample = tmp_path / "sample.txt"
    sample.write_bytes(b"stream me")

    request = SimpleNamespace(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        scope_id="scope-1",
        object_identity="/finance/sample.txt",
        scan_options={"customMetadata": "tenant=acme"},
        content_source=ContentSource(mode="original"),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(
                local_path=sample,
                content_length=128,
                details={"reader": "connector_proxy", "endpointUrl": "http://127.0.0.1:8620/filesystem/read_file"},
            )

    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.verdict == "Benign"
    assert request.scan_options["_dsx_scanner_metadata"]["source"] == "dsxa"
    assert request.scan_options["_dsx_scanner_metadata"]["reader"] == "connector_proxy"
    assert request.scan_options["_dsx_scanner_metadata"]["contentSourceMode"] == "original"
    assert request.scan_options["_dsx_scanner_metadata"]["readerElapsedMs"] >= 0
    assert request.scan_options["_dsx_scanner_metadata"]["scannerEngineElapsedMs"] == 1.234
    custom_metadata = captured["kwargs"]["custom_metadata"]
    assert "object-identity:/finance/sample.txt" in custom_metadata
    assert "integration-id:filesystem-local" in custom_metadata
    assert "scope-id:scope-1" in custom_metadata
    assert "job-id:job-1" in custom_metadata
    assert "job-item-id:item-1" in custom_metadata
    assert "reader:connector_proxy" in custom_metadata
    assert "connector-endpoint:http://127.0.0.1:8620/filesystem/read_file" in custom_metadata
    assert "user-meta:tenant=acme" in custom_metadata
    assert captured["data"] == b"stream me"
    assert FakeClient.instances == 1


def test_execute_scan_via_dsxa_can_use_per_task_client_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.auth_token", "token")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.timeout_seconds", 30.0)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.verify_tls", True)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.protected_entity", 1)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker._SCANNER_CLIENT_SCOPE", "per-task")

    class FakeClient:
        instances = 0
        closes = 0

        def __init__(self, **kwargs):
            FakeClient.instances += 1
            self.kwargs = kwargs

        async def aclose(self):
            FakeClient.closes += 1

        async def scan_binary_stream(self, data, **kwargs):
            _ = b"".join([chunk async for chunk in data])
            return SimpleNamespace(
                scan_guid=f"scan-{FakeClient.instances}",
                verdict=SimpleNamespace(value="Benign"),
                verdict_details=SimpleNamespace(model_dump=lambda **kw: {"reason": "clean"}),
                file_info=SimpleNamespace(model_dump=lambda **kw: {"file_type": "Text"}, file_type="Text"),
                protected_entity=kwargs.get("protected_entity"),
                scan_duration_in_microseconds=1234,
                dsxconnect_request_elapsed_ms=None,
                dsxconnect_read_elapsed_ms=None,
                dsxconnect_dsxa_elapsed_ms=None,
                container_files_scanned=0,
                container_files_scanned_size=0,
                x_custom_metadata=None,
                last_update_time=None,
            )

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )
    sample = tmp_path / "sample.txt"
    sample.write_bytes(b"stream me")

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(
                local_path=sample,
                content_length=128,
                details={"reader": "connector_proxy"},
            )

    def request_for(index: int):
        return SimpleNamespace(
            job_id="job-1",
            job_item_id=f"item-{index}",
            integration_id="filesystem-local",
            scope_id=None,
            object_identity=f"/finance/sample-{index}.txt",
            scan_options={},
            content_source=ContentSource(mode="original"),
        )

    asyncio.run(execute_scan_via_dsxa(request_for(1), FakeReader()))
    asyncio.run(execute_scan_via_dsxa(request_for(2), FakeReader()))

    assert FakeClient.instances == 2
    assert FakeClient.closes == 2


def test_execute_scan_via_dsxa_reuses_client_and_streams_each_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    payloads: list[bytes] = []

    class FakeClient:
        instances = 0

        def __init__(self, **kwargs):
            FakeClient.instances += 1

        async def scan_binary_stream(self, data, **kwargs):
            payloads.append(b"".join([chunk async for chunk in data]))
            return _fake_benign_dsxa_response(scan_guid=f"scan-{len(payloads)}")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    class FakeReader:
        def __init__(self, path: Path):
            self.path = path

        async def acquire(self, _request):
            return SimpleNamespace(local_path=self.path, content_length=self.path.stat().st_size, details={"reader": "local_path"})

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))

    first_result = asyncio.run(execute_scan_via_dsxa(request, FakeReader(first)))
    second_result = asyncio.run(execute_scan_via_dsxa(request, FakeReader(second)))

    assert first_result.scan_guid == "scan-1"
    assert second_result.scan_guid == "scan-2"
    assert payloads == [b"first", b"second"]
    assert FakeClient.instances == 1


def test_execute_scan_via_dsxa_streams_reader_content_without_local_path(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    captured: dict[str, object] = {}

    async def content_stream():
        yield b"proxied "
        yield b"bytes"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def scan_binary_stream(self, data, **kwargs):
            captured["data"] = b"".join([chunk async for chunk in data])
            return _fake_benign_dsxa_response(scan_guid="scan-stream-1")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(
                local_path=None,
                content_stream=content_stream(),
                content_length=13,
                details={"reader": "connector_proxy", "source": "connector_proxy_http_stream"},
            )

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))
    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.scan_guid == "scan-stream-1"
    assert captured["data"] == b"proxied bytes"
    assert request.scan_options["_dsx_scanner_metadata"]["reader"] == "connector_proxy"


def test_execute_scan_via_dsxa_can_scan_by_path_without_streaming_bytes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.transport", "by_path")
    captured: dict[str, object] = {}
    artifact = tmp_path / "sample.txt"
    artifact.write_bytes(b"do not upload")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def scan_by_path(self, stream_path, **kwargs):
            captured["stream_path"] = stream_path
            captured["kwargs"] = kwargs
            return _fake_benign_dsxa_response(scan_guid="scan-by-path-1")

        async def scan_binary_stream(self, data, **kwargs):
            raise AssertionError("binary stream transport should not be used")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=artifact.stat().st_size, details={"reader": "local_path"})

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))
    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.scan_guid == "scan-by-path-1"
    assert captured["stream_path"] == str(artifact)
    assert request.scan_options["_dsx_scanner_metadata"]["transport"] == "by_path"


def test_execute_scan_via_dsxa_polls_scan_by_path_until_terminal(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.transport", "by_path")
    artifact = tmp_path / "sample.txt"
    artifact.write_bytes(b"path")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def scan_by_path(self, stream_path, **kwargs):
            return SimpleNamespace(scan_guid="scan-by-path-pending", verdict="Scanning")

        async def poll_scan_by_path(self, scan_guid, **kwargs):
            return _fake_benign_dsxa_response(scan_guid=scan_guid)

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=artifact.stat().st_size, details={"reader": "local_path"})

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))
    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.scan_guid == "scan-by-path-pending"
    assert result.verdict == "Benign"


def _fake_benign_dsxa_response(**overrides):
    payload = {
        "scan_guid": "scan-1",
        "verdict": SimpleNamespace(value="Benign"),
        "verdict_details": SimpleNamespace(model_dump=lambda **kw: {"reason": "clean"}),
        "file_info": SimpleNamespace(model_dump=lambda **kw: {"file_type": "Text"}, file_type="Text"),
        "protected_entity": None,
        "scan_duration_in_microseconds": 1234,
        "dsxconnect_request_elapsed_ms": None,
        "dsxconnect_read_elapsed_ms": None,
        "dsxconnect_dsxa_elapsed_ms": None,
        "container_files_scanned": 0,
        "container_files_scanned_size": 0,
        "x_custom_metadata": None,
        "last_update_time": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_execute_scan_via_dsxa_deletes_owned_reader_artifact_after_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    artifact = tmp_path / "owned-success.bin"
    artifact.write_bytes(b"abc")

    class FakeClient:
        calls = 0

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            FakeClient.calls += 1
            assert b"".join([chunk async for chunk in data]) == b"abc"
            return _fake_benign_dsxa_response()

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=3, cleanup_local_path=True, details={"reader": "connector_proxy"})

    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.verdict == "Benign"
    assert not artifact.exists()
    assert FakeClient.calls == 1


def test_execute_scan_via_dsxa_deletes_owned_reader_artifact_after_scanner_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    artifact = tmp_path / "owned-failure.bin"
    artifact.write_bytes(b"abc")

    class FakeDsxaError(Exception):
        pass

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            raise FakeDsxaError("connection reset")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, FakeDsxaError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=3, cleanup_local_path=True, details={"reader": "connector_proxy"})

    with pytest.raises(RuntimeError):
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert not artifact.exists()


def test_execute_scan_via_dsxa_preserves_non_owned_reader_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    artifact = tmp_path / "local-path.bin"
    artifact.write_bytes(b"abc")

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            return _fake_benign_dsxa_response()

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    request = SimpleNamespace(scan_options={}, content_source=ContentSource(mode="original"))

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=3, cleanup_local_path=False, details={"reader": "local_path"})

    asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert artifact.exists()


def test_execute_scan_via_dsxa_maps_auth_error_terminal(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.auth_token", "token")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.timeout_seconds", 30.0)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.verify_tls", True)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.protected_entity", 1)

    class FakeAuthError(Exception):
        pass

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            raise FakeAuthError("bad token")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, RuntimeError, FakeAuthError, RuntimeError, RuntimeError, RuntimeError),
    )

    request = SimpleNamespace(
        scan_options={},
        content_source=ContentSource(mode="original"),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=Path("/tmp/sample.txt"), content_length=128, details={"reader": "local_path"})

    with pytest.raises(TerminalScanError) as exc:
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert exc.value.code == "scanner_auth_failed"


def test_execute_scan_via_dsxa_maps_transport_error_retryable(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.auth_token", "token")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.timeout_seconds", 30.0)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.verify_tls", True)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.protected_entity", 1)

    class FakeDsxaError(Exception):
        pass

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            raise FakeDsxaError("connection reset by peer")

    monkeypatch.setattr(
        "dsx_connect_ng.workers.scan_worker._import_dsxa_client",
        lambda: (FakeClient, object, FakeDsxaError, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    request = SimpleNamespace(
        scan_options={},
        content_source=ContentSource(mode="original"),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=Path("/tmp/sample.txt"), content_length=128, details={"reader": "local_path"})

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert "scanner_transport_failure" in str(exc.value)


def test_execute_scan_via_dsxa_skips_oversize_by_size_hint(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.max_file_size_bytes", 100)

    request = SimpleNamespace(
        read_hint={"sizeInBytes": 101},
        scan_options={},
        content_source=ContentSource(mode="original"),
    )

    class FakeReader:
        async def acquire(self, _request):
            raise AssertionError("reader should not be called for oversize size hint")

    with pytest.raises(TerminalScanError) as exc:
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert exc.value.code == "content_too_large"
    assert exc.value.details["enforcement"] == "size_hint"


def test_execute_scan_via_dsxa_skips_oversize_after_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.max_file_size_bytes", 100)
    artifact = tmp_path / "owned-oversize.bin"
    artifact.write_bytes(b"x" * 101)

    request = SimpleNamespace(
        read_hint={},
        scan_options={},
        content_source=ContentSource(mode="original"),
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(local_path=artifact, content_length=101, cleanup_local_path=True, details={"reader": "connector_proxy"})

    with pytest.raises(TerminalScanError) as exc:
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert exc.value.code == "content_too_large"
    assert exc.value.details["enforcement"] == "read_result"
    assert not artifact.exists()
