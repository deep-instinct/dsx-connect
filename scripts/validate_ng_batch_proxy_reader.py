#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from validate_ng_proxy_reader import EICAR_SAMPLE, ensure_integration, get_batch_job, _get_json, _json_request
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.validate_ng_batch_proxy_reader
    from scripts.validate_ng_proxy_reader import EICAR_SAMPLE, ensure_integration, get_batch_job, _get_json, _json_request


def submit_batch(
    *,
    api_base_url: str,
    integration_id: str,
    sample_paths: list[Path],
    delivery_connector: str,
    scan_only: bool,
) -> dict:
    items = []
    for sample_path in sample_paths:
        policy_decision = {}
        if not scan_only:
            policy_decision["delivery_target"] = {
                "connector": delivery_connector,
            }
        items.append(
            {
                "object_identity": str(sample_path),
                "payload": {
                    "readerStrategy": "proxy",
                    "path": str(sample_path),
                    "policyDecision": policy_decision,
                },
            }
        )
    payload = {
        "integration_id": integration_id,
        "items": items,
    }
    status, response = _json_request("POST", f"{api_base_url}/execution/jobs/batch", payload)
    if status >= 400:
        raise SystemExit(f"batch submit failed: status={status} payload={json.dumps(response)}")
    return response


def poll_items(
    *,
    api_base_url: str,
    job_id: str,
    expected_count: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> list[dict]:
    deadline = time.time() + timeout_seconds
    last_payload: dict | list = {}
    max_scanning = 0
    while time.time() < deadline:
        status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/items")
        if status >= 400:
            raise SystemExit(f"job item poll failed: status={status} payload={json.dumps(payload)}")
        last_payload = payload
        items = payload if isinstance(payload, list) else []
        terminal = sum(1 for item in items if item.get("state") in {"completed", "failed", "cancelled"})
        scanning = sum(1 for item in items if item.get("scan_stage", {}).get("state") == "running")
        max_scanning = max(max_scanning, scanning)
        print(
            json.dumps(
                {
                    "event": "batch_poll_progress",
                    "job_id": job_id,
                    "expected_items": expected_count,
                    "observed_items": len(items),
                    "terminal_items": terminal,
                    "scanning_items": scanning,
                    "max_scanning_items": max_scanning,
                    "states": [item.get("state") for item in items],
                }
            ),
            flush=True,
        )
        if len(items) == expected_count and terminal == expected_count:
            for item in items:
                item.setdefault("_validation", {})
                item["_validation"]["max_scanning_items"] = max_scanning
            return items
        time.sleep(poll_interval_seconds)
    raise SystemExit(f"timed out waiting for batch job items to reach terminal state: last_payload={json.dumps(last_payload)}")


def materialize_sample_files(
    *,
    sample_dir: Path,
    sample_prefix: str,
    sample_kind: str,
    sample_content_prefix: str,
    sample_content: str,
    item_count: int,
) -> list[Path]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_paths: list[Path] = []
    resolved_sample_content = EICAR_SAMPLE if sample_kind == "eicar" else sample_content
    for idx in range(item_count):
        sample_path = sample_dir / f"{sample_prefix}-{idx + 1}.txt"
        content = resolved_sample_content if sample_kind == "eicar" else f"{sample_content_prefix} {idx + 1}\n"
        sample_path.write_text(content, encoding="utf-8")
        sample_paths.append(sample_path)
    return sample_paths


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def compute_scan_stage_interval_overlap(items: list[dict[str, Any]]) -> int:
    events: list[tuple[datetime, int]] = []
    for item in items:
        scan_stage = item.get("scan_stage") or {}
        started_at = _parse_timestamp(scan_stage.get("started_at"))
        completed_at = _parse_timestamp(scan_stage.get("completed_at"))
        if started_at is None or completed_at is None or completed_at < started_at:
            continue
        events.append((started_at, 1))
        events.append((completed_at, -1))
    if not events:
        return 0
    current = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        current += delta
        if current > maximum:
            maximum = current
    return maximum


def enforce_concurrency_expectations(
    *,
    observed_max_scanning_items: int,
    min_concurrent_scans: int = 0,
    max_concurrent_scans: int | None = None,
) -> None:
    if observed_max_scanning_items < min_concurrent_scans:
        raise SystemExit(
            "batch concurrency validation failed: "
            f"observed max_scanning_items={observed_max_scanning_items} < required minimum {min_concurrent_scans}"
        )
    if max_concurrent_scans is not None and observed_max_scanning_items > max_concurrent_scans:
        raise SystemExit(
            "batch concurrency validation failed: "
            f"observed max_scanning_items={observed_max_scanning_items} > allowed maximum {max_concurrent_scans}"
        )


def load_result_sink_events(*, result_sink_path: Path, job_id: str) -> list[dict[str, Any]]:
    if not result_sink_path.exists():
        raise SystemExit(f"result sink validation failed: file not found: {result_sink_path}")
    events: list[dict[str, Any]] = []
    for line in result_sink_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        payload = json.loads(raw)
        if payload.get("job_id") == job_id:
            events.append(payload)
    return events


def validate_result_sink_events(
    *,
    events: list[dict[str, Any]],
    expected_job_id: str,
    expected_object_identities: list[str],
    expect_scan_results: int,
    expect_workflow_summaries: int,
) -> dict[str, Any]:
    scan_events = [event for event in events if event.get("event_type") == "scan_result"]
    workflow_events = [event for event in events if event.get("event_type") == "workflow_summary"]
    if len(scan_events) != expect_scan_results:
        raise SystemExit(
            "result sink validation failed: "
            f"expected {expect_scan_results} scan_result events, observed {len(scan_events)}"
        )
    if len(workflow_events) != expect_workflow_summaries:
        raise SystemExit(
            "result sink validation failed: "
            f"expected {expect_workflow_summaries} workflow_summary events, observed {len(workflow_events)}"
        )

    expected_identities = set(expected_object_identities)
    observed_identities = {event.get("object_identity") for event in events}
    if observed_identities != expected_identities:
        raise SystemExit(
            "result sink validation failed: "
            f"object_identity mismatch expected={sorted(expected_identities)} observed={sorted(observed_identities)}"
        )

    for event in events:
        if event.get("schema_version") != "1.0":
            raise SystemExit("result sink validation failed: schema_version must be 1.0")
        if event.get("job_id") != expected_job_id:
            raise SystemExit("result sink validation failed: unexpected job_id in result sink event")
        if event.get("object_identity") not in expected_identities:
            raise SystemExit("result sink validation failed: unexpected object_identity in result sink event")

    for event in scan_events:
        if event.get("verdict") is None:
            raise SystemExit("result sink validation failed: scan_result event missing verdict")
        if event.get("scan_guid") is None:
            raise SystemExit("result sink validation failed: scan_result event missing scan_guid")
        if event.get("content_source_mode") is None:
            raise SystemExit("result sink validation failed: scan_result event missing content_source_mode")
        if "workflow_summary" in event:
            raise SystemExit("result sink validation failed: scan_result event must not include workflow_summary")

    for event in workflow_events:
        summary = event.get("workflow_summary")
        if not isinstance(summary, dict):
            raise SystemExit("result sink validation failed: workflow_summary event missing workflow_summary payload")
        scan = summary.get("scan") or {}
        if scan.get("verdict") is None:
            raise SystemExit("result sink validation failed: workflow_summary event missing scan verdict")

    return {
        "total_events": len(events),
        "scan_result_events": len(scan_events),
        "workflow_summary_events": len(workflow_events),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a multi-item dsx-connect-ng proxy-reader batch and validate item expansion.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8091/api/v1")
    parser.add_argument("--connector-base-url", default="http://127.0.0.1:8620")
    parser.add_argument("--connector-name", default="filesystem-connector")
    parser.add_argument("--integration-id", default="filesystem-local")
    parser.add_argument(
        "--sample-dir",
        default=str(Path.home() / ".dsx-connect-local" / "filesystem-connector" / "data" / "scan" / "batch-validation"),
    )
    parser.add_argument("--sample-prefix", default="proxy-batch-sample")
    parser.add_argument("--sample-kind", choices=["benign", "eicar"], default="benign")
    parser.add_argument("--sample-content-prefix", default="proxy batch validation sample")
    parser.add_argument("--sample-content", default="proxy batch validation sample\n")
    parser.add_argument("--item-count", type=int, default=3)
    parser.add_argument("--delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-only", action="store_true", help="emit scan_result only and skip workflow_summary")
    parser.add_argument("--poll", action="store_true", help="poll all job items until terminal state")
    parser.add_argument("--poll-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--min-concurrent-scans", type=int, default=0, help="require at least this many scan items to be observed running concurrently")
    parser.add_argument("--max-concurrent-scans", type=int, default=None, help="fail if more than this many scan items are observed running concurrently")
    parser.add_argument("--result-sink-path", default=None, help="optional json_lines result sink file to validate for this batch job")
    args = parser.parse_args(argv)
    if (args.min_concurrent_scans or args.max_concurrent_scans is not None or args.result_sink_path) and not args.poll:
        parser.error("--min-concurrent-scans/--max-concurrent-scans/--result-sink-path require --poll")
    return args


def main() -> None:
    args = parse_args()
    sample_dir = Path(args.sample_dir).expanduser().resolve()
    sample_paths = materialize_sample_files(
        sample_dir=sample_dir,
        sample_prefix=args.sample_prefix,
        sample_kind=args.sample_kind,
        sample_content_prefix=args.sample_content_prefix,
        sample_content=args.sample_content,
        item_count=args.item_count,
    )

    integration = ensure_integration(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        connector_base_url=args.connector_base_url,
        connector_name=args.connector_name,
        summary_delivery_connector=args.delivery_connector,
        scan_delivery_connector=args.scan_delivery_connector,
        scan_only=args.scan_only,
    )
    batch = submit_batch(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        sample_paths=sample_paths,
        delivery_connector=args.delivery_connector,
        scan_only=args.scan_only,
    )

    result: dict = {
        "integration_id": integration.get("integration_id"),
        "job_id": batch.get("job", {}).get("job_id"),
        "job_state": batch.get("job", {}).get("state"),
        "scan_only": args.scan_only,
        "sample_kind": args.sample_kind,
        "submitted_item_count": args.item_count,
        "sample_paths": [str(path) for path in sample_paths],
    }

    if args.poll and result["job_id"]:
        items = poll_items(
            api_base_url=args.api_base_url,
            job_id=result["job_id"],
            expected_count=args.item_count,
            timeout_seconds=args.poll_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        batch_state = get_batch_job(api_base_url=args.api_base_url, job_id=result["job_id"])
        result["job_state"] = batch_state.get("job", {}).get("state", result["job_state"])
        result["item_summary"] = batch_state.get("item_summary")
        result["job_item_ids"] = [item.get("job_item_id") for item in items]
        result["item_states"] = [item.get("state") for item in items]
        result["observed_item_count"] = len(items)
        result["max_scanning_items_polled"] = max((item.get("_validation") or {}).get("max_scanning_items", 0) for item in items)
        result["max_scanning_items_interval"] = compute_scan_stage_interval_overlap(items)
        result["max_scanning_items"] = max(
            result["max_scanning_items_polled"],
            result["max_scanning_items_interval"],
        )
        enforce_concurrency_expectations(
            observed_max_scanning_items=result["max_scanning_items"],
            min_concurrent_scans=args.min_concurrent_scans,
            max_concurrent_scans=args.max_concurrent_scans,
        )
        if args.result_sink_path:
            result_sink_events = load_result_sink_events(
                result_sink_path=Path(args.result_sink_path).expanduser().resolve(),
                job_id=result["job_id"],
            )
            result["result_sink_validation"] = validate_result_sink_events(
                events=result_sink_events,
                expected_job_id=result["job_id"],
                expected_object_identities=[str(path) for path in sample_paths],
                expect_scan_results=args.item_count if args.scan_delivery_connector else 0,
                expect_workflow_summaries=0 if args.scan_only else args.item_count,
            )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
