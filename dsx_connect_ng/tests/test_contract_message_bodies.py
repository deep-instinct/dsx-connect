from dsx_connect_ng.jobs.contracts import MessageEnvelope, PolicyEvaluationRequested, RemediationRequested, ResultSinkEmitRequested, ScanItemRequested


def test_scan_item_requested_from_envelope_parses_typed_payload() -> None:
    envelope = MessageEnvelope(
        message_type="scan_item_requested",
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        payload={
            "content_source": {"mode": "original"},
            "read_hint": {"objectIdentity": "/finance/a.pdf"},
            "scan_options": {"protectedEntity": 1},
        },
    )

    message = ScanItemRequested.from_envelope(envelope)

    assert message.content_source.mode == "original"
    assert message.scan_options["protectedEntity"] == 1


def test_policy_evaluation_requested_from_envelope_parses_typed_scan_result() -> None:
    envelope = MessageEnvelope(
        message_type="policy_evaluation_requested",
        job_id="job-2",
        job_item_id="item-2",
        object_identity="/finance/bad.exe",
        payload={
            "scan_result": {"verdict": "Malicious", "scanGuid": "scan-2"},
            "item_payload": {"source": "sharepoint"},
        },
    )

    message = PolicyEvaluationRequested.from_envelope(envelope)

    assert message.scan_result.verdict == "Malicious"
    assert message.scan_result.scan_guid == "scan-2"


def test_policy_evaluation_requested_can_convert_to_policy_handoff_request() -> None:
    envelope = MessageEnvelope(
        message_type="policy_evaluation_requested",
        job_id="job-2",
        job_item_id="item-2",
        integration_id="filesystem-local",
        scope_id="scope-1",
        object_identity="/finance/bad.exe",
        payload={
            "scan_result": {"verdict": "Malicious", "scanGuid": "scan-2"},
            "item_payload": {
                "content_source": {"mode": "cached", "locator": "/tmp/a.bin"},
                "delivery_requirements": {"wait_for_dianna": True},
            },
        },
    )

    message = PolicyEvaluationRequested.from_envelope(envelope)
    handoff = message.as_policy_handoff_request()

    assert handoff.scan_result.scan_guid == "scan-2"
    assert handoff.content_source.mode == "cached"
    assert handoff.delivery_requirements.wait_for_dianna is True


def test_remediation_requested_from_envelope_parses_typed_payload() -> None:
    envelope = MessageEnvelope(
        message_type="remediation_requested",
        job_id="job-3",
        job_item_id="item-3",
        object_identity="/finance/bad.exe",
        payload={
            "scan_result": {"verdict": "Malicious"},
            "remediation_plan": {"action": "quarantine"},
        },
    )

    message = RemediationRequested.from_envelope(envelope)

    assert message.scan_result.verdict == "Malicious"
    assert message.remediation_plan.remediation_plan["action"] == "quarantine"


def test_result_sink_emit_requested_from_envelope_parses_typed_payload() -> None:
    envelope = MessageEnvelope(
        message_type="result_sink_emit_requested",
        job_id="job-4",
        job_item_id="item-4",
        object_identity="/finance/a.pdf",
        payload={
            "result_type": "scan_result",
            "result_payload": {"verdict": "Benign"},
            "final_result": {"scan": {"verdict": "Benign"}},
            "delivery_target": {"connector": "sharepoint"},
        },
    )

    message = ResultSinkEmitRequested.from_envelope(envelope)

    assert message.result_type == "scan_result"
    assert message.result_payload["verdict"] == "Benign"
    assert message.final_result["scan"]["verdict"] == "Benign"
    assert message.delivery_target.delivery_target["connector"] == "sharepoint"


def test_legacy_result_delivery_requested_from_envelope_still_parses() -> None:
    envelope = MessageEnvelope(
        message_type="result_delivery_requested",
        job_id="job-4",
        job_item_id="item-4",
        object_identity="/finance/a.pdf",
        payload={
            "result_type": "scan_result",
            "result_payload": {"verdict": "Benign"},
            "final_result": {"scan": {"verdict": "Benign"}},
            "delivery_target": {"connector": "sharepoint"},
        },
    )

    message = ResultSinkEmitRequested.from_envelope(envelope)

    assert message.message_type == "result_sink_emit_requested"
