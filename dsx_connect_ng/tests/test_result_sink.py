import asyncio
import json

from dsx_connect_ng.result_sink.bootstrap import build_result_sink
from dsx_connect_ng.jobs.contracts import ResultSinkEmitRequested
from dsx_connect_ng.result_sink.json_lines import JsonLinesResultSink
from dsx_connect_ng.result_sink.models import ResultSinkEvent
from dsx_connect_ng.result_sink.stdout import StdoutResultSink
from dsx_connect_ng.workers.delivery_worker import build_result_sink_executor


def test_result_sink_event_maps_result_sink_emit_request() -> None:
    request = ResultSinkEmitRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        scope_id="scope-1",
        object_identity="/finance/a.pdf",
        result_type="scan_result",
        result_payload={"verdict": "Benign"},
        final_result={
            "scan": {
                "verdict": "Benign",
                "scan_guid": "scan-1",
                "file_info": {
                    "file_type": "Unknown",
                    "file_hash": "abc123",
                },
            },
            "scanMetadata": {
                "source": "dsxa",
                "reader": "connector_proxy",
                "protectedEntity": 1,
                "requestElapsedMs": 10.0,
                "readElapsedMs": 3.0,
                "dsxaElapsedMs": 7.0,
            },
            "contentSource": {"mode": "original"},
        },
        delivery_target={"delivery_target": {"connector": "sharepoint"}},
    )

    event = ResultSinkEvent.from_result_sink_emit_request(request)

    assert event.event_type == "scan_result"
    assert event.integration_id == "filesystem-local"
    assert event.scope_id == "scope-1"
    assert event.file_hash == "abc123"
    assert event.scan_guid == "scan-1"
    assert event.verdict == "Benign"
    assert event.file_type == "Unknown"
    assert event.content_source_mode == "original"
    assert event.scanner_metadata == {
        "source": "dsxa",
        "reader": "connector_proxy",
        "protectedEntity": 1,
        "requestElapsedMs": 10.0,
        "readElapsedMs": 3.0,
        "dsxaElapsedMs": 7.0,
    }
    assert event.delivery_target["connector"] == "sharepoint"
    assert event.workflow_summary is None


def test_json_lines_result_sink_writes_structured_event(tmp_path) -> None:
    sink_path = tmp_path / "results.jsonl"
    sink = JsonLinesResultSink(sink_path)
    event = ResultSinkEvent(
        event_type="scan_result",
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        payload={"verdict": "Benign"},
    )

    asyncio.run(sink.emit(event))

    lines = sink_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == "1.0"
    assert payload["event_type"] == "scan_result"
    assert payload["payload"]["verdict"] == "Benign"
    assert "workflow_summary" not in payload


def test_result_sink_executor_emits_event_and_returns_delivery_result(tmp_path) -> None:
    sink_path = tmp_path / "results.jsonl"
    sink = JsonLinesResultSink(sink_path)
    executor = build_result_sink_executor(sink)
    request = ResultSinkEmitRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        result_type="workflow_summary",
        final_result={"scan": {"verdict": "Benign"}},
        delivery_target={"delivery_target": {"connector": "sharepoint"}},
    )

    result = asyncio.run(executor(request))

    assert result.outcome == "emitted"
    assert result.destination == "sharepoint"
    payload = json.loads(sink_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["event_type"] == "workflow_summary"
    assert payload["workflow_summary"]["scan"]["verdict"] == "Benign"


def test_build_result_sink_uses_stdout_backend(monkeypatch) -> None:
    from dsx_connect_ng.result_sink import bootstrap

    monkeypatch.setattr(bootstrap.settings.result_sink, "backend", "stdout")

    sink = build_result_sink()

    assert isinstance(sink, StdoutResultSink)
