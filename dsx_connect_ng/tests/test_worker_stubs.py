import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

from dsx_connect_ng.control_plane.models import IntegrationCreate, ProtectedScopeCreate
from dsx_connect_ng.control_plane.repository import InMemoryControlPlaneRepository
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.bus import InMemoryJobBus
from dsx_connect_ng.jobs.contracts import MessageEnvelope, ResultSinkEmitRequested
from dsx_connect_ng.jobs.models import (
    BatchJobSubmitRequest,
    ContentPreservationDecision,
    ContentSource,
    DeliveryDispatchDecision,
    DeliveryResult,
    DeliveryRequirements,
    DiannaResult,
    PolicyDecision,
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
from dsx_connect_ng.workers.remediation_worker import process_remediation_message
from dsx_connect_ng.workers.scan_worker import (
    TerminalScanError,
    execute_scan_via_dsxa,
    map_dsxa_scan_response,
    process_scan_message,
    resolve_local_scan_path,
)


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


async def _fake_policy(request) -> PolicyDecision:
    if request.scan_result.verdict == "Malicious":
        return PolicyDecision(
            remediation_plan={"action": "quarantine"},
            delivery_target={"connector": "sharepoint"},
            request_dianna=True,
            wait_for_dianna_before_delivery=True,
        )
    return PolicyDecision(delivery_target={"connector": "sharepoint"})


async def _fake_policy_without_dianna(request) -> PolicyDecision:
    if request.scan_result.verdict == "Malicious":
        return PolicyDecision(
            remediation_plan={"action": "quarantine"},
            delivery_target={"connector": "sharepoint"},
        )
    return PolicyDecision(delivery_target={"connector": "sharepoint"})


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


def test_scan_worker_processes_message_and_requests_follow_on_work_inline() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    first_message = bus.snapshot()[0]
    assert isinstance(first_message, MessageEnvelope)
    assert first_message.message_type == "scan_item_requested"

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan, evaluate_policy=_fake_policy_engine))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.scan_stage.result is not None
    assert item.scan_stage.result["scan_guid"] == "scan-worker-1"
    assert item.scan_stage.metadata == {}
    assert item.policy_stage.state == "completed"
    published_types = [message.message_type for message in bus.snapshot() if isinstance(message, MessageEnvelope)]
    assert "policy_evaluation_requested" not in published_types
    assert "dianna_analysis_requested" in published_types
    assert "remediation_requested" in published_types


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
    captured = {}

    async def capture_policy_request(request: PolicyHandoffRequest) -> PolicyHandoffDecision:
        captured["policy_context"] = request.policy_context
        captured["item_metadata"] = request.item_metadata
        return await _fake_policy_engine_without_dianna(request)

    asyncio.run(process_scan_message(service, first_message, execute_scan=_fake_scan, evaluate_policy=capture_policy_request))

    assert captured["policy_context"]["integration_config"]["policy"]["policy_id"] == "integration-policy"
    assert captured["policy_context"]["scope_policy"]["policy_id"] == "scope-policy"
    assert captured["policy_context"]["resolved_policy"]["policy_id"] == "scope-policy"
    assert captured["policy_context"]["resolved_policy"]["delivery"]["scan_targets"] == [{"connector": "scope-scan"}]
    assert captured["item_metadata"]["integration"]["integration_id"] == integration.integration_id
    assert captured["item_metadata"]["scope"]["scope_id"] == scope.scope_id


def test_policy_worker_processes_message_and_requests_follow_on_work() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan))
    item = service.list_job_items(job_id=created.job.job_id)[0]
    asyncio.run(service.request_policy_evaluation(item.job_item_id))
    policy_message = bus.snapshot()[-1]

    asyncio.run(process_policy_message(service, policy_message, evaluate_policy=_fake_policy))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.policy_stage.result is not None
    assert item.policy_stage.result["request_dianna"] is True
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
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan, evaluate_policy=_fake_policy_engine_without_dianna))

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


def test_result_sink_worker_processes_message_and_completes_item() -> None:
    repo = InMemoryJobRepository()
    bus = InMemoryJobBus()
    service = JobService(repo=repo, bus=bus)
    created = asyncio.run(
        service.submit_batch_job(BatchJobSubmitRequest(items=[{"object_identity": "/finance/bad.exe"}]))
    )
    scan_message = bus.snapshot()[0]
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan, evaluate_policy=_fake_policy_engine_without_dianna))
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
    delivery_message = next(
        message for message in reversed(bus.snapshot()) if isinstance(message, MessageEnvelope) and message.message_type == "result_sink_emit_requested"
    )

    asyncio.run(process_result_sink_message(service, delivery_message, execute_result_sink=_fake_delivery))

    item = service.list_job_items(job_id=created.job.job_id)[0]
    assert item.remediation_stage.state == "skipped"
    assert item.remediation_stage.result == {"reason": "benign_verdict"}
    assert item.dianna_stage.state == "skipped"
    assert item.dianna_stage.result == {"reason": "not_auto_requested", "details": {"verdict": "Benign"}}
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
    asyncio.run(process_scan_message(service, scan_message, execute_scan=_fake_scan, evaluate_policy=_fake_policy_engine))

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


def test_execute_scan_via_dsxa_enriches_scanner_metadata(monkeypatch) -> None:
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.base_url", "http://scanner.local")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.auth_token", "token")
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.timeout_seconds", 30.0)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.verify_tls", True)
    monkeypatch.setattr("dsx_connect_ng.workers.scan_worker.settings.scanner.protected_entity", 1)
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_file(self, path, **kwargs):
            captured["path"] = path
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
                local_path=Path("/tmp/sample.txt"),
                details={"reader": "connector_proxy", "endpointUrl": "http://127.0.0.1:8620/filesystem/read_file"},
            )

    result = asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert result.verdict == "Benign"
    assert request.scan_options["_dsx_scanner_metadata"]["source"] == "dsxa"
    assert request.scan_options["_dsx_scanner_metadata"]["reader"] == "connector_proxy"
    assert request.scan_options["_dsx_scanner_metadata"]["contentSourceMode"] == "original"
    assert request.scan_options["_dsx_scanner_metadata"]["readerElapsedMs"] >= 0
    custom_metadata = captured["kwargs"]["custom_metadata"]
    assert "object-identity:/finance/sample.txt" in custom_metadata
    assert "integration-id:filesystem-local" in custom_metadata
    assert "scope-id:scope-1" in custom_metadata
    assert "job-id:job-1" in custom_metadata
    assert "job-item-id:item-1" in custom_metadata
    assert "reader:connector_proxy" in custom_metadata
    assert "connector-endpoint:http://127.0.0.1:8620/filesystem/read_file" in custom_metadata
    assert "user-meta:tenant=acme" in custom_metadata


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

        async def scan_file(self, path, **kwargs):
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
            return SimpleNamespace(local_path=Path("/tmp/sample.txt"), details={"reader": "local_path"})

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

        async def scan_file(self, path, **kwargs):
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
            return SimpleNamespace(local_path=Path("/tmp/sample.txt"), details={"reader": "local_path"})

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(execute_scan_via_dsxa(request, FakeReader()))

    assert "scanner_transport_failure" in str(exc.value)
