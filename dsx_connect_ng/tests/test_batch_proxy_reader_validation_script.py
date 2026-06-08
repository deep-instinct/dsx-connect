from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_batch_proxy_reader_script_is_importable_from_repo_root() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    assert module.__name__ == "scripts.validate_ng_batch_proxy_reader"


def test_materialize_sample_files_writes_benign_samples(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    sample_paths = module.materialize_sample_files(
        sample_dir=tmp_path,
        sample_prefix="sample",
        sample_kind="benign",
        sample_content_prefix="benign sample",
        sample_content="ignored for benign\n",
        item_count=2,
    )

    assert [path.name for path in sample_paths] == ["sample-1.txt", "sample-2.txt"]
    assert sample_paths[0].read_text(encoding="utf-8") == "benign sample 1\n"
    assert sample_paths[1].read_text(encoding="utf-8") == "benign sample 2\n"


def test_materialize_sample_files_writes_eicar_samples(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    sample_paths = module.materialize_sample_files(
        sample_dir=tmp_path,
        sample_prefix="sample",
        sample_kind="eicar",
        sample_content_prefix="ignored",
        sample_content="ignored\n",
        item_count=2,
    )

    assert all(path.read_text(encoding="utf-8") == module.EICAR_SAMPLE for path in sample_paths)


def test_list_existing_sample_files_uses_sorted_top_level_files(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.txt").write_text("c", encoding="utf-8")

    sample_paths = module.list_existing_sample_files(sample_dir=tmp_path, item_count=2)

    assert [path.name for path in sample_paths] == ["a.txt", "b.txt"]


def test_enforce_concurrency_expectations_accepts_observed_range() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    module.enforce_concurrency_expectations(
        observed_max_scanning_items=2,
        min_concurrent_scans=2,
        max_concurrent_scans=3,
    )


def test_enforce_concurrency_expectations_rejects_too_little_parallelism() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    with pytest.raises(SystemExit, match="required minimum 2"):
        module.enforce_concurrency_expectations(
            observed_max_scanning_items=1,
            min_concurrent_scans=2,
        )


def test_parse_args_rejects_concurrency_assertions_without_poll() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    with pytest.raises(SystemExit, match="2"):
        module.parse_args(["--min-concurrent-scans", "2"])


def test_load_result_sink_events_filters_by_job_id(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    sink_path = tmp_path / "results.jsonl"
    sink_path.write_text(
        "\n".join(
            [
                '{"job_id":"job-1","event_type":"scan_result","object_identity":"/tmp/a.txt","schema_version":"1.0"}',
                '{"job_id":"job-2","event_type":"scan_result","object_identity":"/tmp/b.txt","schema_version":"1.0"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = module.load_result_sink_events(result_sink_path=sink_path, job_id="job-2")

    assert len(events) == 1
    assert events[0]["job_id"] == "job-2"


def test_validate_result_sink_events_accepts_scan_only_payloads() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    events = [
        {
            "schema_version": "1.0",
            "job_id": "job-1",
            "event_type": "scan_result",
            "object_identity": "/tmp/a.txt",
            "verdict": "Malicious",
            "scan_guid": "scan-1",
            "content_source_mode": "original",
        },
        {
            "schema_version": "1.0",
            "job_id": "job-1",
            "event_type": "scan_result",
            "object_identity": "/tmp/b.txt",
            "verdict": "Malicious",
            "scan_guid": "scan-2",
            "content_source_mode": "original",
        },
    ]

    summary = module.validate_result_sink_events(
        events=events,
        expected_job_id="job-1",
        expected_object_identities=["/tmp/a.txt", "/tmp/b.txt"],
        expect_scan_results=2,
        expect_workflow_summaries=0,
    )

    assert summary == {
        "total_events": 2,
        "scan_result_events": 2,
        "workflow_summary_events": 0,
    }


def test_validate_result_sink_events_accepts_workflow_summary_payloads() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    events = [
        {
            "schema_version": "1.0",
            "job_id": "job-1",
            "event_type": "scan_result",
            "object_identity": "/tmp/a.txt",
            "verdict": "Benign",
            "scan_guid": "scan-1",
            "content_source_mode": "original",
        },
        {
            "schema_version": "1.0",
            "job_id": "job-1",
            "event_type": "workflow_summary",
            "object_identity": "/tmp/a.txt",
            "workflow_summary": {"scan": {"verdict": "Benign"}},
        },
    ]

    summary = module.validate_result_sink_events(
        events=events,
        expected_job_id="job-1",
        expected_object_identities=["/tmp/a.txt"],
        expect_scan_results=1,
        expect_workflow_summaries=1,
    )

    assert summary["workflow_summary_events"] == 1


def test_parse_args_rejects_result_sink_validation_without_poll() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    with pytest.raises(SystemExit, match="2"):
        module.parse_args(["--result-sink-path", "/tmp/results.jsonl"])


def test_parse_args_rejects_detail_polling_when_item_count_exceeds_limit() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    with pytest.raises(SystemExit, match="2"):
        module.parse_args(["--poll", "--poll-mode", "items", "--item-count", "10000", "--items-limit", "5000"])


def test_parse_args_rejects_summary_polling_with_concurrency_assertions() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    with pytest.raises(SystemExit, match="2"):
        module.parse_args(["--poll", "--poll-mode", "summary", "--min-concurrent-scans", "2"])


def test_parse_args_defaults_large_submit_timeout() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    args = module.parse_args([])

    assert args.submit_timeout_seconds == 300.0
    assert args.defer_publish is True
    assert args.reader_strategy == "proxy"


def test_parse_args_can_select_native_reader_strategy() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    args = module.parse_args(["--reader-strategy", "native"])

    assert args.reader_strategy == "native"


def test_parse_args_can_disable_deferred_publish() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")

    args = module.parse_args(["--no-defer-publish"])

    assert args.defer_publish is False


def test_submit_batch_can_request_deferred_publish(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    captured: dict = {}

    def fake_request(method: str, url: str, payload: dict, *, timeout_seconds: float) -> tuple[int, dict]:
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return 200, {"job": {"job_id": "job-1"}}

    sample_path = tmp_path / "sample.txt"
    sample_path.write_text("sample\n", encoding="utf-8")
    monkeypatch.setattr(module, "json_request_with_timeout", fake_request)

    response = module.submit_batch(
        api_base_url="http://api/v1",
        integration_id="integration-a",
        sample_paths=[sample_path],
        delivery_connector="filesystem-local",
        scan_only=True,
        timeout_seconds=12.0,
        defer_publish=True,
        reader_strategy="native",
    )

    assert response["job"]["job_id"] == "job-1"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://api/v1/execution/jobs/batch"
    assert captured["timeout_seconds"] == 12.0
    assert captured["payload"]["payload"] == {"publishMode": "deferred"}
    assert captured["payload"]["items"][0]["payload"]["readerStrategy"] == "native"
    assert captured["payload"]["items"][0]["payload"]["path"] == str(sample_path)


def test_poll_batch_summary_waits_for_terminal_counts(monkeypatch) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    calls = iter(
        [
            {
                "job": {"job_id": "job-1", "state": "running"},
                "item_summary": {"total": 2, "completed": 1, "failed": 0, "cancelled": 0},
            },
            {
                "job": {"job_id": "job-1", "state": "completed"},
                "item_summary": {"total": 2, "completed": 2, "failed": 0, "cancelled": 0},
            },
        ]
    )

    monkeypatch.setattr(module, "get_batch_job", lambda **kwargs: next(calls))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    payload = module.poll_batch_summary(
        api_base_url="http://api",
        job_id="job-1",
        expected_count=2,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert payload["job"]["state"] == "completed"


def test_poll_job_progress_waits_for_terminal_progress(monkeypatch) -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    calls = iter(
        [
            (
                200,
                {
                    "job_id": "job-1",
                    "state": "running",
                    "total_items": 2,
                    "terminal_items": 1,
                    "percent_complete": 50.0,
                },
            ),
            (
                200,
                {
                    "job_id": "job-1",
                    "state": "completed",
                    "total_items": 2,
                    "terminal_items": 2,
                    "percent_complete": 100.0,
                },
            ),
        ]
    )

    monkeypatch.setattr(module, "_get_json", lambda _url: next(calls))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    payload = module.poll_job_progress(
        api_base_url="http://api",
        job_id="job-1",
        expected_count=2,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert payload["percent_complete"] == 100.0


def test_compute_scan_stage_interval_overlap_counts_overlapping_windows() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    items = [
        {
            "scan_stage": {
                "started_at": "2026-05-26T13:00:00+00:00",
                "completed_at": "2026-05-26T13:00:03+00:00",
            }
        },
        {
            "scan_stage": {
                "started_at": "2026-05-26T13:00:01+00:00",
                "completed_at": "2026-05-26T13:00:04+00:00",
            }
        },
        {
            "scan_stage": {
                "started_at": "2026-05-26T13:00:05+00:00",
                "completed_at": "2026-05-26T13:00:06+00:00",
            }
        },
    ]

    assert module.compute_scan_stage_interval_overlap(items) == 2


def test_compute_scan_stage_interval_overlap_ignores_missing_timestamps() -> None:
    module = importlib.import_module("scripts.validate_ng_batch_proxy_reader")
    items = [
        {"scan_stage": {"started_at": "2026-05-26T13:00:00+00:00", "completed_at": None}},
        {"scan_stage": {"started_at": None, "completed_at": "2026-05-26T13:00:01+00:00"}},
    ]

    assert module.compute_scan_stage_interval_overlap(items) == 0
