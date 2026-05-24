#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EICAR_SAMPLE = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*\n"


def _json_request(method: str, url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urlopen(req, timeout=15.0) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return exc.code, payload
    except URLError as exc:
        raise SystemExit(f"request failed: url={url} error={exc.reason}. Is dsx-connect-ng running and reachable?") from exc


def _get_json(url: str) -> tuple[int, dict | list]:
    req = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=15.0) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return exc.code, payload
    except URLError as exc:
        raise SystemExit(f"request failed: url={url} error={exc.reason}. Is dsx-connect-ng running and reachable?") from exc


def ensure_integration(
    *,
    api_base_url: str,
    integration_id: str,
    connector_base_url: str,
    connector_name: str,
    summary_delivery_connector: str,
    scan_delivery_connector: str | None,
    scan_only: bool,
) -> dict:
    delivery_config: dict = {
        "workflow_summary_targets": [],
    }
    if not scan_only:
        delivery_config["workflow_summary_targets"] = [{"connector": summary_delivery_connector}]
    if scan_delivery_connector:
        delivery_config["scan_targets"] = [{"connector": scan_delivery_connector}]

    create_payload = {
        "integration_id": integration_id,
        "platform": "filesystem",
        "platform_key": integration_id,
        "display_name": "Filesystem Local",
        "capability_read": True,
        "config": {
            "reader": {
                "default_strategy": "proxy",
                "proxy": {
                    "base_url": connector_base_url,
                    "connector_name": connector_name,
                    "auth_mode": "none",
                },
            },
            "policy": {
                "result_delivery_policy": {
                    "scan": "all_results",
                    "remediation": "all_outcomes",
                    "dianna": "completed_only",
                },
                "delivery": delivery_config,
            },
        },
    }
    status, payload = _json_request("POST", f"{api_base_url}/control-plane/integrations", create_payload)
    if status == 409:
        patch_payload = {
            "display_name": "Filesystem Local",
            "capability_read": True,
            "config": create_payload["config"],
        }
        status, payload = _json_request("PATCH", f"{api_base_url}/control-plane/integrations/{integration_id}", patch_payload)
    if status >= 400:
        raise SystemExit(f"integration request failed: status={status} payload={json.dumps(payload)}")
    return payload


def submit_batch(
    *,
    api_base_url: str,
    integration_id: str,
    sample_path: Path,
    delivery_connector: str,
    scan_only: bool,
) -> dict:
    policy_decision = {}
    if not scan_only:
        policy_decision["delivery_target"] = {
            "connector": delivery_connector,
        }
    payload = {
        "integration_id": integration_id,
        "items": [
            {
                "object_identity": str(sample_path),
                "payload": {
                    "readerStrategy": "proxy",
                    "path": str(sample_path),
                    "policyDecision": policy_decision,
                },
            }
        ],
    }
    status, response = _json_request("POST", f"{api_base_url}/execution/jobs/batch", payload)
    if status >= 400:
        raise SystemExit(f"batch submit failed: status={status} payload={json.dumps(response)}")
    return response


def poll_first_item(
    *,
    api_base_url: str,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict:
    deadline = time.time() + timeout_seconds
    last_payload: dict | list = {}
    while time.time() < deadline:
        status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/items")
        if status >= 400:
            raise SystemExit(f"job item poll failed: status={status} payload={json.dumps(payload)}")
        last_payload = payload
        items = payload if isinstance(payload, list) else []
        if items:
            item = items[0]
            state = item.get("state")
            print(
                json.dumps(
                    {
                        "event": "poll_progress",
                        "job_id": job_id,
                        "job_item_id": item.get("job_item_id"),
                        "item_state": state,
                        "scan_stage": item.get("scan_stage", {}).get("state"),
                        "policy_stage": item.get("policy_stage", {}).get("state"),
                        "remediation_stage": item.get("remediation_stage", {}).get("state"),
                        "delivery_stage": item.get("delivery_stage", {}).get("state"),
                        "dianna_stage": item.get("dianna_stage", {}).get("state"),
                    }
                ),
                flush=True,
            )
            if state in {"completed", "failed", "cancelled"}:
                return item
        time.sleep(poll_interval_seconds)
    raise SystemExit(f"timed out waiting for first job item to reach terminal state: last_payload={json.dumps(last_payload)}")


def get_batch_job(
    *,
    api_base_url: str,
    job_id: str,
) -> dict:
    status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/batch")
    if status >= 400:
        raise SystemExit(f"batch job fetch failed: status={status} payload={json.dumps(payload)}")
    if not isinstance(payload, dict):
        raise SystemExit(f"unexpected batch job response: {json.dumps(payload)}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and submit a dsx-connect-ng proxy-reader validation batch.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8091/api/v1")
    parser.add_argument("--connector-base-url", default="http://127.0.0.1:8620")
    parser.add_argument("--connector-name", default="filesystem-connector")
    parser.add_argument("--integration-id", default="filesystem-local")
    parser.add_argument(
        "--sample-path",
        default=str(Path.home() / ".dsx-connect-local" / "filesystem-connector" / "data" / "scan" / "proxy-reader-sample.txt"),
    )
    parser.add_argument("--sample-kind", choices=["benign", "eicar"], default="benign")
    parser.add_argument("--sample-content", default="proxy-reader validation sample\n")
    parser.add_argument("--delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-delivery-connector", default="filesystem-local")
    parser.add_argument("--scan-only", action="store_true", help="emit scan_result only and skip workflow_summary")
    parser.add_argument("--poll", action="store_true", help="poll the first job item until terminal state")
    parser.add_argument("--poll-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sample_path = Path(args.sample_path).expanduser().resolve()
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_content = EICAR_SAMPLE if args.sample_kind == "eicar" else args.sample_content
    sample_path.write_text(sample_content, encoding="utf-8")

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
        sample_path=sample_path,
        delivery_connector=args.delivery_connector,
        scan_only=args.scan_only,
    )
    result: dict = {
        "sample_path": str(sample_path),
        "sample_kind": args.sample_kind,
        "integration_id": integration.get("integration_id"),
        "job_id": batch.get("job", {}).get("job_id"),
        "job_state": batch.get("job", {}).get("state"),
        "scan_only": args.scan_only,
    }
    if args.poll and result["job_id"]:
        item = poll_first_item(
            api_base_url=args.api_base_url,
            job_id=result["job_id"],
            timeout_seconds=args.poll_timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        batch_state = get_batch_job(api_base_url=args.api_base_url, job_id=result["job_id"])
        result["job_state"] = batch_state.get("job", {}).get("state", result["job_state"])
        result["job_item_id"] = item.get("job_item_id")
        result["item_state"] = item.get("state")
        result["scan_stage"] = item.get("scan_stage")
        result["policy_stage"] = item.get("policy_stage")
        result["remediation_stage"] = item.get("remediation_stage")
        result["delivery_stage"] = item.get("delivery_stage")
        result["dianna_stage"] = item.get("dianna_stage")

    print(
        json.dumps(result, indent=2)
    )


if __name__ == "__main__":
    main()
