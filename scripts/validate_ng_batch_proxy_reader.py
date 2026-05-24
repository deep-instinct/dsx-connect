#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from validate_ng_proxy_reader import ensure_integration, get_batch_job, _get_json, _json_request


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


def parse_args() -> argparse.Namespace:
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
    parser.add_argument("--sample-content-prefix", default="proxy batch validation sample")
    parser.add_argument("--item-count", type=int, default=3)
    parser.add_argument("--delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-only", action="store_true", help="emit scan_result only and skip workflow_summary")
    parser.add_argument("--poll", action="store_true", help="poll all job items until terminal state")
    parser.add_argument("--poll-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sample_dir = Path(args.sample_dir).expanduser().resolve()
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_paths: list[Path] = []
    for idx in range(args.item_count):
        sample_path = sample_dir / f"{args.sample_prefix}-{idx + 1}.txt"
        sample_path.write_text(f"{args.sample_content_prefix} {idx + 1}\n", encoding="utf-8")
        sample_paths.append(sample_path)

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
        result["max_scanning_items"] = max((item.get("_validation") or {}).get("max_scanning_items", 0) for item in items)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
