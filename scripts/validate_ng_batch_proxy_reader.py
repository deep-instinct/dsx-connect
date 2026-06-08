#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from validate_ng_proxy_reader import EICAR_SAMPLE, ensure_integration, get_batch_job, _get_json
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.validate_ng_batch_proxy_reader
    from scripts.validate_ng_proxy_reader import EICAR_SAMPLE, ensure_integration, get_batch_job, _get_json


def json_request_with_timeout(method: str, url: str, payload: dict, *, timeout_seconds: float) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return exc.code, payload
    except (TimeoutError, URLError) as exc:
        raise SystemExit(
            f"request failed: url={url} timeout_seconds={timeout_seconds} error={exc}. "
            "For large batches, increase --submit-timeout-seconds or reduce --item-count."
        ) from exc


def submit_batch(
    *,
    api_base_url: str,
    integration_id: str,
    sample_paths: list[Path],
    delivery_connector: str,
    scan_only: bool,
    timeout_seconds: float,
    defer_publish: bool,
    reader_strategy: str,
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
                    "readerStrategy": reader_strategy,
                    "path": str(sample_path),
                    "scanOnly": scan_only,
                    "policyDecision": policy_decision,
                },
            }
        )
    payload = {
        "integration_id": integration_id,
        "items": items,
    }
    if defer_publish:
        payload["payload"] = {"publishMode": "deferred"}
    status, response = json_request_with_timeout(
        "POST",
        f"{api_base_url}/execution/jobs/batch",
        payload,
        timeout_seconds=timeout_seconds,
    )
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
    items_limit: int,
    verbose_states: bool,
) -> list[dict]:
    deadline = time.time() + timeout_seconds
    last_payload: dict | list = {}
    max_scanning = 0
    while time.time() < deadline:
        status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/items?limit={items_limit}")
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
                    "states": [item.get("state") for item in items] if verbose_states else None,
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


def poll_batch_summary(
    *,
    api_base_url: str,
    job_id: str,
    expected_count: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        payload = get_batch_job(api_base_url=api_base_url, job_id=job_id)
        last_payload = payload
        summary = payload.get("item_summary") or {}
        terminal = sum(int(summary.get(key) or 0) for key in ("completed", "failed", "cancelled"))
        print(
            json.dumps(
                {
                    "event": "batch_summary_progress",
                    "job_id": job_id,
                    "job_state": (payload.get("job") or {}).get("state"),
                    "expected_items": expected_count,
                    "terminal_items": terminal,
                    "summary": summary,
                }
            ),
            flush=True,
        )
        if int(summary.get("total") or 0) == expected_count and terminal == expected_count:
            return payload
        time.sleep(poll_interval_seconds)
    raise SystemExit(f"timed out waiting for batch job summary to reach terminal state: last_payload={json.dumps(last_payload)}")


def poll_job_progress(
    *,
    api_base_url: str,
    job_id: str,
    expected_count: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/progress")
        if status >= 400:
            raise SystemExit(f"job progress poll failed: status={status} payload={json.dumps(payload)}")
        last_payload = payload if isinstance(payload, dict) else {}
        terminal = int(last_payload.get("terminal_items") or 0)
        print(
            json.dumps(
                {
                    "event": "job_progress",
                    "job_id": job_id,
                    "job_state": last_payload.get("state"),
                    "expected_items": expected_count,
                    "terminal_items": terminal,
                    "percent_complete": last_payload.get("percent_complete"),
                    "throughput": last_payload.get("throughput"),
                    "latency": last_payload.get("latency"),
                    "backlog": last_payload.get("backlog"),
                    "runtime": last_payload.get("runtime"),
                    "bottleneck_hints": last_payload.get("bottleneck_hints"),
                }
            ),
            flush=True,
        )
        if int(last_payload.get("total_items") or 0) == expected_count and terminal == expected_count:
            return last_payload
        time.sleep(poll_interval_seconds)
    raise SystemExit(f"timed out waiting for job progress to reach terminal state: last_payload={json.dumps(last_payload)}")


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


def list_existing_sample_files(*, sample_dir: Path, item_count: int) -> list[Path]:
    if not sample_dir.is_dir():
        raise SystemExit(f"sample directory does not exist: {sample_dir}")
    sample_paths = sorted(path for path in sample_dir.iterdir() if path.is_file())
    if len(sample_paths) < item_count:
        raise SystemExit(f"sample directory only contains {len(sample_paths)} files; requested {item_count}")
    return sample_paths[:item_count]


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
    parser.add_argument("--use-existing-samples", action="store_true", help="read existing top-level files from --sample-dir instead of writing generated samples")
    parser.add_argument("--submit-timeout-seconds", type=float, default=300.0, help="timeout for the initial batch submit request")
    parser.add_argument(
        "--defer-publish",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="create pending outbox records and let the relay publish scan requests after submission (default: enabled)",
    )
    parser.add_argument("--delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-delivery-connector", default="filesystem-local")
    parser.add_argument(
        "--reader-strategy",
        choices=["proxy", "native"],
        default="proxy",
        help="reader strategy to place on each submitted scan item; native bypasses the connector proxy for local path reads",
    )
    parser.add_argument("--scan-only", action="store_true", help="emit scan_result only and skip workflow_summary")
    parser.add_argument("--poll", action="store_true", help="poll all job items until terminal state")
    parser.add_argument("--poll-mode", choices=["auto", "items", "progress", "summary"], default="auto", help="items fetches job item details; progress polls the job progress API; summary polls aggregate counts only")
    parser.add_argument("--poll-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--items-limit", type=int, default=5000, help="job item detail fetch limit when poll-mode=items")
    parser.add_argument("--verbose-item-states", action="store_true", help="include every item state in each item polling progress event")
    parser.add_argument("--min-concurrent-scans", type=int, default=0, help="require at least this many scan items to be observed running concurrently")
    parser.add_argument("--max-concurrent-scans", type=int, default=None, help="fail if more than this many scan items are observed running concurrently")
    parser.add_argument("--result-sink-path", default=None, help="optional json_lines result sink file to validate for this batch job")
    args = parser.parse_args(argv)
    if (args.min_concurrent_scans or args.max_concurrent_scans is not None or args.result_sink_path) and not args.poll:
        parser.error("--min-concurrent-scans/--max-concurrent-scans/--result-sink-path require --poll")
    if (args.min_concurrent_scans or args.max_concurrent_scans is not None or args.result_sink_path) and args.poll_mode == "summary":
        parser.error("--min-concurrent-scans/--max-concurrent-scans/--result-sink-path require item detail polling")
    if args.poll_mode == "items" and args.item_count > args.items_limit:
        parser.error("--poll-mode=items requires --items-limit >= --item-count")
    return args


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()
    sample_dir = Path(args.sample_dir).expanduser().resolve()
    materialize_started_at = time.perf_counter()
    if args.use_existing_samples:
        sample_paths = list_existing_sample_files(sample_dir=sample_dir, item_count=args.item_count)
    else:
        sample_paths = materialize_sample_files(
            sample_dir=sample_dir,
            sample_prefix=args.sample_prefix,
            sample_kind=args.sample_kind,
            sample_content_prefix=args.sample_content_prefix,
            sample_content=args.sample_content,
            item_count=args.item_count,
        )
    materialize_elapsed_seconds = time.perf_counter() - materialize_started_at

    integration = ensure_integration(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        connector_base_url=args.connector_base_url,
        connector_name=args.connector_name,
        summary_delivery_connector=args.delivery_connector,
        scan_delivery_connector=args.scan_delivery_connector,
        scan_only=args.scan_only,
    )
    submit_started_at = time.perf_counter()
    batch = submit_batch(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        sample_paths=sample_paths,
        delivery_connector=args.delivery_connector,
        scan_only=args.scan_only,
        timeout_seconds=args.submit_timeout_seconds,
        defer_publish=args.defer_publish,
        reader_strategy=args.reader_strategy,
    )
    submit_elapsed_seconds = time.perf_counter() - submit_started_at

    result: dict = {
        "integration_id": integration.get("integration_id"),
        "job_id": batch.get("job", {}).get("job_id"),
        "job_state": batch.get("job", {}).get("state"),
        "scan_only": args.scan_only,
        "defer_publish": args.defer_publish,
        "reader_strategy": args.reader_strategy,
        "sample_kind": args.sample_kind,
        "submitted_item_count": args.item_count,
        "sample_path_count": len(sample_paths),
        "sample_path_preview": [str(path) for path in sample_paths[:10]],
        "materialize_elapsed_seconds": round(materialize_elapsed_seconds, 3),
        "submit_elapsed_seconds": round(submit_elapsed_seconds, 3),
    }

    if args.poll and result["job_id"]:
        poll_mode = args.poll_mode
        if poll_mode == "auto":
            poll_mode = "items" if args.item_count <= args.items_limit else "progress"
        result["poll_mode"] = poll_mode
        poll_started_at = time.perf_counter()
        items: list[dict[str, Any]] = []
        if poll_mode == "items":
            items = poll_items(
                api_base_url=args.api_base_url,
                job_id=result["job_id"],
                expected_count=args.item_count,
                timeout_seconds=args.poll_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                items_limit=args.items_limit,
                verbose_states=args.verbose_item_states,
            )
            batch_state = get_batch_job(api_base_url=args.api_base_url, job_id=result["job_id"])
        elif poll_mode == "progress":
            progress_state = poll_job_progress(
                api_base_url=args.api_base_url,
                job_id=result["job_id"],
                expected_count=args.item_count,
                timeout_seconds=args.poll_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            result["progress"] = progress_state
            batch_state = get_batch_job(api_base_url=args.api_base_url, job_id=result["job_id"])
        else:
            batch_state = poll_batch_summary(
                api_base_url=args.api_base_url,
                job_id=result["job_id"],
                expected_count=args.item_count,
                timeout_seconds=args.poll_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        poll_elapsed_seconds = time.perf_counter() - poll_started_at
        result["job_state"] = batch_state.get("job", {}).get("state", result["job_state"])
        result["item_summary"] = batch_state.get("item_summary")
        result["poll_elapsed_seconds"] = round(poll_elapsed_seconds, 3)
        result["items_per_second_after_submit"] = round(args.item_count / poll_elapsed_seconds, 3) if poll_elapsed_seconds else None
        if items:
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

    total_elapsed_seconds = time.perf_counter() - started_at
    result["total_elapsed_seconds"] = round(total_elapsed_seconds, 3)
    result["items_per_second_total"] = round(args.item_count / total_elapsed_seconds, 3) if total_elapsed_seconds else None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
