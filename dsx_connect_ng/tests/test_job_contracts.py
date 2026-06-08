from dsx_connect_ng.jobs.contracts import DiannaAnalysisRequested, PolicyEvaluationRequested, RemediationRequested, ResultSinkEmitRequested, ScanItemRequested


def test_scan_item_requested_converts_to_generic_envelope() -> None:
    message = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        scope_id="scope-1",
        object_identity="/finance/a.pdf",
        idempotency_key="idem-1",
        read_hint={"connector": "sharepoint"},
        scan_options={"protectedEntity": 1},
    )

    envelope = message.as_envelope()

    assert envelope.message_type == "scan_item_requested"
    assert envelope.job_id == "job-1"
    assert envelope.job_item_id == "item-1"
    assert envelope.payload["read_hint"]["connector"] == "sharepoint"
    assert envelope.payload["scan_options"]["protectedEntity"] == 1


def test_dianna_analysis_requested_converts_to_generic_envelope() -> None:
    message = DiannaAnalysisRequested(
        job_id="job-2",
        job_item_id="item-2",
        object_identity="/finance/bad.exe",
        request_reason="manual",
        scan_result={"verdict": "Malicious"},
    )

    envelope = message.as_envelope()

    assert envelope.message_type == "dianna_analysis_requested"
    assert envelope.payload["request_reason"] == "manual"
    assert envelope.payload["scan_result"]["verdict"] == "Malicious"


def test_policy_evaluation_requested_converts_to_generic_envelope() -> None:
    message = PolicyEvaluationRequested(
        job_id="job-2b",
        job_item_id="item-2b",
        integration_id="integration-2",
        scope_id="scope-2",
        object_identity="/finance/bad.exe",
        scan_result={"verdict": "Malicious"},
        item_payload={"hint": "x"},
    )

    envelope = message.as_envelope()

    assert envelope.message_type == "policy_evaluation_requested"
    assert envelope.payload["scan_result"]["verdict"] == "Malicious"
    assert envelope.payload["item_payload"]["hint"] == "x"


def test_result_sink_emit_requested_converts_to_generic_envelope() -> None:
    message = ResultSinkEmitRequested(
        job_id="job-3",
        job_item_id="item-3",
        object_identity="/finance/a.pdf",
        final_result={"verdict": "Benign"},
        delivery_target={"connector": "sharepoint"},
    )

    envelope = message.as_envelope()

    assert envelope.message_type == "result_sink_emit_requested"
    assert envelope.payload["final_result"]["verdict"] == "Benign"
    assert envelope.payload["delivery_target"]["connector"] == "sharepoint"


def test_remediation_requested_converts_to_generic_envelope() -> None:
    message = RemediationRequested(
        job_id="job-4",
        job_item_id="item-4",
        integration_id="integration-4",
        scope_id="scope-4",
        object_identity="/finance/bad.exe",
        content_source={"mode": "original", "locator": "/finance/bad.exe"},
        scan_result={"verdict": "Malicious"},
        remediation_plan={"action": "quarantine"},
    )

    envelope = message.as_envelope()

    assert envelope.message_type == "remediation_requested"
    assert envelope.integration_id == "integration-4"
    assert envelope.scope_id == "scope-4"
    assert envelope.payload["content_source"]["locator"] == "/finance/bad.exe"
    assert envelope.payload["scan_result"]["verdict"] == "Malicious"
    assert envelope.payload["remediation_plan"]["action"] == "quarantine"


def test_remediation_requested_builds_normalized_connector_request() -> None:
    message = RemediationRequested(
        job_id="job-4",
        job_item_id="item-4",
        integration_id="integration-4",
        scope_id="scope-4",
        object_identity="/finance/bad.exe",
        content_source={"mode": "original", "locator": "/finance/bad.exe"},
        scan_result={"verdict": "Malicious"},
        remediation_plan={"action": "quarantine", "targetPath": "tenant-quarantine", "tag": True},
    )

    connector_request = message.as_connector_remediation_request()

    assert connector_request.action == "movetag"
    assert connector_request.destination == {"path": "tenant-quarantine", "filename": "bad.exe_item4"}
    assert connector_request.tags == {"Verdict": "Malicious"}
