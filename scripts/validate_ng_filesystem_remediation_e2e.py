#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

try:
    from validate_ng_proxy_reader import EICAR_SAMPLE, _get_json, _json_request
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.validate_ng_filesystem_remediation_e2e
    from scripts.validate_ng_proxy_reader import EICAR_SAMPLE, _get_json, _json_request


TERMINAL_ITEM_STATES = {"completed", "failed", "cancelled"}


def build_integration_payload(
    *,
    integration_id: str,
    connector_base_url: str,
    connector_name: str,
) -> dict[str, Any]:
    return {
        "integration_id": integration_id,
        "platform": "filesystem",
        "platform_key": integration_id,
        "display_name": "Filesystem E2E Validation",
        "capability_read": True,
        "capability_remediate": True,
        "config": {
            "reader": {
                "default_strategy": "proxy",
                "proxy": {
                    "base_url": connector_base_url,
                    "connector_name": connector_name,
                    "auth_mode": "none",
                },
            },
            "remediation": {
                "supports_delete": True,
                "supports_move": True,
                "supports_tag": True,
                "supports_movetag": True,
            },
        },
    }


def build_scope_policy(*, quarantine_dir: Path, tag_on_quarantine: bool) -> dict[str, Any]:
    return {
        "malicious_verdict": {
            "action": "quarantine",
            "quarantine_target": {
                "path": str(quarantine_dir),
            },
            "tag_on_quarantine": tag_on_quarantine,
        }
    }


def ensure_integration(
    *,
    api_base_url: str,
    integration_id: str,
    connector_base_url: str,
    connector_name: str,
) -> dict[str, Any]:
    create_payload = build_integration_payload(
        integration_id=integration_id,
        connector_base_url=connector_base_url,
        connector_name=connector_name,
    )
    status, payload = _json_request("POST", f"{api_base_url}/control-plane/integrations", create_payload)
    if status == 409:
        patch_payload = {
            "display_name": create_payload["display_name"],
            "capability_read": True,
            "capability_remediate": True,
            "config": create_payload["config"],
        }
        status, payload = _json_request("PATCH", f"{api_base_url}/control-plane/integrations/{integration_id}", patch_payload)
    if status >= 400:
        raise SystemExit(f"integration request failed: status={status} payload={json.dumps(payload)}")
    return payload


def ensure_scope(
    *,
    api_base_url: str,
    scope_id: str,
    integration_id: str,
    resource_selector: str,
    quarantine_dir: Path,
    tag_on_quarantine: bool,
) -> dict[str, Any]:
    create_payload = {
        "scope_id": scope_id,
        "integration_id": integration_id,
        "scope_type": "path",
        "resource_selector": resource_selector,
        "display_name": f"Filesystem E2E Scope: {resource_selector}",
        "mode": "full_scan",
        "post_scan_policy": build_scope_policy(
            quarantine_dir=quarantine_dir,
            tag_on_quarantine=tag_on_quarantine,
        ),
    }
    status, payload = _json_request("POST", f"{api_base_url}/control-plane/scopes", create_payload)
    if status == 409:
        patch_payload = {
            "display_name": create_payload["display_name"],
            "mode": create_payload["mode"],
            "post_scan_policy": create_payload["post_scan_policy"],
        }
        status, payload = _json_request("PATCH", f"{api_base_url}/control-plane/scopes/{scope_id}", patch_payload)
    if status >= 400:
        raise SystemExit(f"scope request failed: status={status} payload={json.dumps(payload)}")
    return payload


def submit_batch(
    *,
    api_base_url: str,
    integration_id: str,
    scope_id: str,
    sample_path: Path,
) -> dict[str, Any]:
    payload = {
        "integration_id": integration_id,
        "scope_id": scope_id,
        "items": [
            {
                "object_identity": str(sample_path),
                "payload": {
                    "readerStrategy": "proxy",
                    "path": str(sample_path),
                },
            }
        ],
    }
    status, response = _json_request("POST", f"{api_base_url}/execution/jobs/batch", payload)
    if status >= 400:
        raise SystemExit(f"batch submit failed: status={status} payload={json.dumps(response)}")
    return response


def poll_item(
    *,
    api_base_url: str,
    job_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
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
            print(
                json.dumps(
                    {
                        "event": "remediation_e2e_poll_progress",
                        "job_id": job_id,
                        "job_item_id": item.get("job_item_id"),
                        "item_state": item.get("state"),
                        "scan_stage": item.get("scan_stage", {}).get("state"),
                        "policy_stage": item.get("policy_stage", {}).get("state"),
                        "remediation_stage": item.get("remediation_stage", {}).get("state"),
                        "delivery_stage": item.get("delivery_stage", {}).get("state"),
                    }
                ),
                flush=True,
            )
            if item.get("state") in TERMINAL_ITEM_STATES:
                return item
        time.sleep(poll_interval_seconds)
    raise SystemExit(f"timed out waiting for job item to reach terminal state: last_payload={json.dumps(last_payload)}")


def get_batch_job(*, api_base_url: str, job_id: str) -> dict[str, Any]:
    status, payload = _get_json(f"{api_base_url}/execution/jobs/{job_id}/batch")
    if status >= 400:
        raise SystemExit(f"batch job fetch failed: status={status} payload={json.dumps(payload)}")
    if not isinstance(payload, dict):
        raise SystemExit(f"unexpected batch job response: {json.dumps(payload)}")
    return payload


def expected_quarantine_path(*, quarantine_dir: Path, sample_name: str) -> Path:
    return quarantine_dir / sample_name


def expected_tag_sidecar_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.dsx.tags.json")


def remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def validate_outcome(
    *,
    sample_path: Path,
    quarantined_path: Path,
    tag_sidecar_path: Path,
    tag_on_quarantine: bool,
    item: dict[str, Any],
) -> dict[str, Any]:
    if item.get("state") != "completed":
        raise SystemExit(f"validation failed: expected completed item state, observed {item.get('state')}")

    scan_stage = item.get("scan_stage") or {}
    scan_result = scan_stage.get("result") or {}
    if scan_result.get("verdict") != "Malicious":
        raise SystemExit(
            "validation failed: expected Malicious scan verdict, "
            f"observed {json.dumps(scan_result)}"
        )

    if (item.get("policy_stage") or {}).get("state") != "completed":
        raise SystemExit("validation failed: policy stage did not complete")
    if (item.get("remediation_stage") or {}).get("state") != "completed":
        raise SystemExit("validation failed: remediation stage did not complete")

    remediation_result = (item.get("remediation_stage") or {}).get("result") or {}
    if remediation_result.get("action") != "quarantine":
        raise SystemExit(
            "validation failed: expected remediation action quarantine, "
            f"observed {json.dumps(remediation_result)}"
        )
    if remediation_result.get("outcome") != "succeeded":
        raise SystemExit(
            "validation failed: expected remediation outcome succeeded, "
            f"observed {json.dumps(remediation_result)}"
        )
    connector_action = ((remediation_result.get("details") or {}).get("connectorAction") or {}).get("item_action")
    if connector_action != "movetag":
        raise SystemExit(
            "validation failed: expected connector action movetag, "
            f"observed {json.dumps(remediation_result)}"
        )

    if sample_path.exists():
        raise SystemExit(f"validation failed: source file still exists after quarantine: {sample_path}")
    if not quarantined_path.exists():
        raise SystemExit(f"validation failed: quarantined file not found: {quarantined_path}")

    if tag_on_quarantine:
        if not tag_sidecar_path.exists():
            raise SystemExit(f"validation failed: tag sidecar not found: {tag_sidecar_path}")
        tags = json.loads(tag_sidecar_path.read_text(encoding="utf-8"))
        if tags.get("Verdict") != "Malicious":
            raise SystemExit(
                "validation failed: expected Verdict=Malicious tag sidecar, "
                f"observed {json.dumps(tags)}"
            )
    return {
        "scan_verdict": scan_result.get("verdict"),
        "remediation_result": remediation_result,
        "connector_action": connector_action,
        "quarantined_path": str(quarantined_path),
        "tag_sidecar_path": str(tag_sidecar_path) if tag_on_quarantine else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_state_root = Path.home() / ".dsx-connect-local" / "filesystem-connector" / "data"
    parser = argparse.ArgumentParser(
        description="Validate end-to-end dsx-connect-ng filesystem remediation with proxy read, policy, and quarantine."
    )
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8091/api/v1")
    parser.add_argument("--connector-base-url", default="http://127.0.0.1:8620")
    parser.add_argument("--connector-name", default="filesystem-connector")
    parser.add_argument("--integration-id", default="filesystem-e2e-validation")
    parser.add_argument("--scope-id", default="filesystem-e2e-validation-scope")
    parser.add_argument("--scan-dir", default=str(default_state_root / "scan" / "ng-e2e"))
    parser.add_argument("--quarantine-dir", default=str(default_state_root / "quarantine" / "ng-e2e"))
    parser.add_argument("--sample-name", default="eicar.txt")
    parser.add_argument("--poll-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--tag-on-quarantine", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    scan_dir = Path(args.scan_dir).expanduser().resolve()
    quarantine_dir = Path(args.quarantine_dir).expanduser().resolve()
    sample_path = scan_dir / args.sample_name
    quarantined_path = expected_quarantine_path(quarantine_dir=quarantine_dir, sample_name=args.sample_name)
    tag_sidecar_path = expected_tag_sidecar_path(quarantined_path)

    scan_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    remove_if_exists(sample_path)
    remove_if_exists(quarantined_path)
    remove_if_exists(tag_sidecar_path)
    sample_path.write_text(EICAR_SAMPLE, encoding="utf-8")

    integration = ensure_integration(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        connector_base_url=args.connector_base_url,
        connector_name=args.connector_name,
    )
    scope = ensure_scope(
        api_base_url=args.api_base_url,
        scope_id=args.scope_id,
        integration_id=args.integration_id,
        resource_selector=str(scan_dir),
        quarantine_dir=quarantine_dir,
        tag_on_quarantine=args.tag_on_quarantine,
    )
    batch = submit_batch(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        scope_id=scope.get("scope_id") or args.scope_id,
        sample_path=sample_path,
    )
    job_id = (batch.get("job") or {}).get("job_id")
    if not job_id:
        raise SystemExit(f"batch submit returned no job_id: {json.dumps(batch)}")

    item = poll_item(
        api_base_url=args.api_base_url,
        job_id=job_id,
        timeout_seconds=args.poll_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    batch_state = get_batch_job(api_base_url=args.api_base_url, job_id=job_id)
    verification = validate_outcome(
        sample_path=sample_path,
        quarantined_path=quarantined_path,
        tag_sidecar_path=tag_sidecar_path,
        tag_on_quarantine=args.tag_on_quarantine,
        item=item,
    )

    result = {
        "integration_id": integration.get("integration_id"),
        "scope_id": scope.get("scope_id"),
        "job_id": job_id,
        "job_state": (batch_state.get("job") or {}).get("state"),
        "job_item_id": item.get("job_item_id"),
        "item_state": item.get("state"),
        "scan_stage": item.get("scan_stage"),
        "policy_stage": item.get("policy_stage"),
        "remediation_stage": item.get("remediation_stage"),
        "delivery_stage": item.get("delivery_stage"),
        "sample_path": str(sample_path),
        **verification,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
