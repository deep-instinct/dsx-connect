from pydantic import ValidationError

from dsx_connect_ng.jobs.models import (
    ExecutionAdmissionStatus,
    ContentPreservationDecision,
    DeliveryResult,
    DeliveryDispatchDecision,
    DeliveryStageUpdateRequest,
    DeliveryRequirements,
    DiannaResult,
    DiannaStageUpdateRequest,
    HealthSignal,
    PolicyDecision,
    PolicyHandoffDecision,
    PolicyHandoffRequest,
    PolicyStageResult,
    PolicyStageUpdateRequest,
    RemediationResult,
    StageApplicabilityDecision,
    StageResultDeliveryPolicy,
    RemediationStageUpdateRequest,
    ScanDispatchGateDecision,
    ScanResult,
    ScanStageUpdateRequest,
)


def test_policy_stage_update_request_requires_decision_on_completed() -> None:
    try:
        PolicyStageUpdateRequest(state="completed")
    except ValidationError as exc:
        assert "completed_policy_stage_requires_decision" in str(exc)
    else:
        raise AssertionError("expected validation error for missing policy decision")


def test_policy_stage_update_request_requires_error_on_failed() -> None:
    try:
        PolicyStageUpdateRequest(state="failed")
    except ValidationError as exc:
        assert "failed_policy_stage_requires_error" in str(exc)
    else:
        raise AssertionError("expected validation error for missing policy error")


def test_policy_stage_update_request_converts_to_stage_update_request() -> None:
    payload = PolicyStageUpdateRequest(
        state="completed",
        decision=PolicyDecision(
            remediation_plan={"action": "quarantine"},
            delivery_target={"connector": "sharepoint"},
            request_dianna=True,
            wait_for_dianna_before_delivery=True,
        ),
    )

    normalized = payload.as_stage_update_request()

    assert normalized.state == "completed"
    assert normalized.result is not None
    assert normalized.result["remediation_plan"]["action"] == "quarantine"
    assert normalized.result["delivery_target"]["connector"] == "sharepoint"
    assert normalized.result["request_dianna"] is True


def test_policy_handoff_request_carries_typed_scan_and_delivery_context() -> None:
    payload = PolicyHandoffRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        object_identity="/finance/a.pdf",
        delivery_requirements=DeliveryRequirements(wait_for_dianna=True),
        scan_result=ScanResult(verdict="Benign", scanGuid="scan-1"),
        item_payload={"foo": "bar"},
    )

    assert payload.scan_result.scan_guid == "scan-1"
    assert payload.delivery_requirements.wait_for_dianna is True
    assert payload.item_payload["foo"] == "bar"


def test_policy_handoff_decision_carries_stage_specific_delivery_policy() -> None:
    decision = PolicyHandoffDecision(
        policy_stage_result=PolicyStageResult(policy_id="policy-1", decision_trace={"matched_rule": "allow"}),
        remediation=StageApplicabilityDecision(state="skipped", reason="benign_verdict"),
        dianna=StageApplicabilityDecision(state="skipped", reason="not_auto_requested"),
        delivery=DeliveryDispatchDecision(
            request_now=True,
            targets=[{"connector": "sharepoint"}],
            scan_targets=[{"connector": "scan-sink"}],
            workflow_summary_targets=[{"connector": "summary-sink"}],
        ),
        content_preservation=ContentPreservationDecision(mode="cached", reason="dianna_follow_up"),
        result_delivery_policy=StageResultDeliveryPolicy(
            scan="all_results",
            remediation="all_outcomes",
            dianna="completed_only",
        ),
    )

    assert decision.policy_stage_result.policy_id == "policy-1"
    assert decision.delivery.request_now is True
    assert decision.delivery.scan_targets[0]["connector"] == "scan-sink"
    assert decision.result_delivery_policy.scan == "all_results"
    assert decision.content_preservation.mode == "cached"


def test_scan_stage_update_request_requires_scan_result_on_completed() -> None:
    try:
        ScanStageUpdateRequest(state="completed")
    except ValidationError as exc:
        assert "completed_scan_stage_requires_scan_result" in str(exc)
    else:
        raise AssertionError("expected validation error for missing scan result")


def test_scan_stage_update_request_requires_error_on_failed() -> None:
    try:
        ScanStageUpdateRequest(state="failed")
    except ValidationError as exc:
        assert "failed_scan_stage_requires_error" in str(exc)
    else:
        raise AssertionError("expected validation error for missing scan error")


def test_scan_stage_update_request_converts_to_stage_update_request() -> None:
    payload = ScanStageUpdateRequest(
        state="completed",
        scan_result=ScanResult(
            verdict="Malicious",
            scanGuid="scan-123",
            fileType="PE32FileType",
            scanDurationUs=125000,
            details={"engine": "dsxa"},
            scannerMetadata={"protectedEntity": 1},
        ),
    )

    normalized = payload.as_stage_update_request()

    assert normalized.state == "completed"
    assert normalized.result is not None
    assert normalized.result["verdict"] == "Malicious"
    assert normalized.result["scan_guid"] == "scan-123"
    assert normalized.result["file_info"]["file_type"] == "PE32FileType"
    assert normalized.result["scan_duration_in_microseconds"] == 125000


def test_remediation_stage_update_request_requires_result_on_completed() -> None:
    try:
        RemediationStageUpdateRequest(state="completed")
    except ValidationError as exc:
        assert "completed_remediation_stage_requires_result" in str(exc)
    else:
        raise AssertionError("expected validation error for missing remediation result")


def test_remediation_stage_update_request_converts_to_stage_update_request() -> None:
    payload = RemediationStageUpdateRequest(
        state="completed",
        remediation_result=RemediationResult(
            action="quarantine",
            outcome="succeeded",
            targetPath="/quarantine/file.exe",
        ),
    )

    normalized = payload.as_stage_update_request()

    assert normalized.result is not None
    assert normalized.result["action"] == "quarantine"
    assert normalized.result["targetPath"] == "/quarantine/file.exe"


def test_dianna_stage_update_request_requires_result_on_completed() -> None:
    try:
        DiannaStageUpdateRequest(state="completed")
    except ValidationError as exc:
        assert "completed_dianna_stage_requires_result" in str(exc)
    else:
        raise AssertionError("expected validation error for missing dianna result")


def test_dianna_stage_update_request_converts_to_stage_update_request() -> None:
    payload = DiannaStageUpdateRequest(
        state="completed",
        dianna_result=DiannaResult(
            analysisId="analysis-1",
            status="completed",
        ),
    )

    normalized = payload.as_stage_update_request()

    assert normalized.result is not None
    assert normalized.result["analysisId"] == "analysis-1"
    assert normalized.result["status"] == "completed"


def test_delivery_stage_update_request_requires_result_on_completed() -> None:
    try:
        DeliveryStageUpdateRequest(state="completed")
    except ValidationError as exc:
        assert "completed_delivery_stage_requires_result" in str(exc)
    else:
        raise AssertionError("expected validation error for missing delivery result")


def test_delivery_stage_update_request_converts_to_stage_update_request() -> None:
    payload = DeliveryStageUpdateRequest(
        state="completed",
        delivery_result=DeliveryResult(
            destination="sharepoint",
            outcome="delivered",
            externalReference="ref-1",
        ),
    )

    normalized = payload.as_stage_update_request()

    assert normalized.result is not None
    assert normalized.result["destination"] == "sharepoint"
    assert normalized.result["externalReference"] == "ref-1"


def test_execution_admission_status_supports_global_and_integration_gate_state() -> None:
    status = ExecutionAdmissionStatus(
        default_action="accept_and_dispatch",
        scan_dispatch=[
            ScanDispatchGateDecision(
                scope="global",
                admission_action="accept_and_hold",
                dispatch_action="hold",
                reason="scanner_auth_invalid",
            ),
            ScanDispatchGateDecision(
                scope="integration",
                scope_id="filesystem-local",
                admission_action="accept_and_hold",
                dispatch_action="hold",
                reason="reader_config_invalid",
            ),
        ],
        active_signals=[
            HealthSignal(
                signal_type="scanner_auth_invalid",
                subsystem="scanner",
                scope="global",
                reason="scanner_auth_invalid",
            ),
            HealthSignal(
                signal_type="reader_config_invalid",
                subsystem="reader",
                scope="integration",
                scope_id="filesystem-local",
                reason="reader_config_invalid",
            ),
        ],
    )

    assert status.scan_dispatch[0].dispatch_action == "hold"
    assert status.scan_dispatch[1].scope_id == "filesystem-local"
    assert status.active_signals[1].subsystem == "reader"
