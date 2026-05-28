#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from validate_ng_proxy_reader import EICAR_SAMPLE, _get_json, _json_request
except ModuleNotFoundError:  # pragma: no cover - exercised when imported as scripts.validate_ng_gcs_remediation_e2e
    from scripts.validate_ng_proxy_reader import EICAR_SAMPLE, _get_json, _json_request

if TYPE_CHECKING:
    from connectors.google_cloud_storage.gcs_client import GCSClient


TERMINAL_ITEM_STATES = {"completed", "failed", "cancelled"}


def default_env_file_candidates() -> list[Path]:
    root = Path.home() / ".dsx-connect-local"
    return [
        root / "google-cloud-storage-connector-2g" / ".env.local",
        root / "google-cloud-storage-connector" / ".env.local",
        root / "google-cloud-storage-debug" / ".env.local",
        root / "google-cloud-storage-connector-desktop" / ".env.local",
        root / "google-cloud-storage-connector-compose" / ".env.local",
    ]


def read_env_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def resolve_env_file(explicit_env_file: str | None) -> Path:
    if explicit_env_file:
        return Path(explicit_env_file).expanduser().resolve()
    for candidate in default_env_file_candidates():
        if candidate.exists():
            env_map = read_env_map(candidate)
            asset = env_map.get("DSXCONNECTOR_ASSET") or env_map.get("ASSET") or ""
            if asset.strip():
                return candidate
    existing = next((candidate for candidate in default_env_file_candidates() if candidate.exists()), None)
    if existing is not None:
        return existing
    return default_env_file_candidates()[0]


def resolve_credentials_path(credentials_path: str | None, *, env_file: Path) -> str | None:
    value = str(credentials_path or "").strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str((env_file.parent / candidate).resolve())


def parse_asset(asset: str) -> tuple[str, str]:
    value = asset.strip().strip("/")
    if not value:
        raise SystemExit("gcs validation requires a non-empty bucket asset")
    if "/" not in value:
        return value, ""
    bucket, prefix = value.split("/", 1)
    return bucket.strip(), prefix.strip("/")


def join_key(*parts: str) -> str:
    return "/".join(part.strip("/") for part in parts if part and part.strip("/"))


def build_integration_payload(
    *,
    integration_id: str,
    platform_key: str,
    connector_base_url: str,
    connector_name: str,
) -> dict[str, Any]:
    return {
        "integration_id": integration_id,
        "platform": "gcs",
        "platform_key": platform_key,
        "display_name": "GCS E2E Validation",
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


def build_scope_policy(*, quarantine_prefix: str, tag_on_quarantine: bool) -> dict[str, Any]:
    return {
        "malicious_verdict": {
            "action": "quarantine",
            "quarantine_target": {
                "path": quarantine_prefix,
            },
            "tag_on_quarantine": tag_on_quarantine,
        }
    }


def ensure_integration(
    *,
    api_base_url: str,
    integration_id: str,
    platform_key: str,
    connector_base_url: str,
    connector_name: str,
) -> dict[str, Any]:
    create_payload = build_integration_payload(
        integration_id=integration_id,
        platform_key=platform_key,
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
    quarantine_prefix: str,
    tag_on_quarantine: bool,
) -> dict[str, Any]:
    create_payload = {
        "scope_id": scope_id,
        "integration_id": integration_id,
        "scope_type": "path",
        "resource_selector": resource_selector,
        "display_name": f"GCS E2E Scope: {resource_selector}",
        "mode": "full_scan",
        "post_scan_policy": build_scope_policy(
            quarantine_prefix=quarantine_prefix,
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
    object_key: str,
) -> dict[str, Any]:
    payload = {
        "integration_id": integration_id,
        "scope_id": scope_id,
        "items": [
            {
                "object_identity": object_key,
                "payload": {
                    "readerStrategy": "proxy",
                    "path": object_key,
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
                        "event": "gcs_remediation_e2e_poll_progress",
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


def build_gcs_client(*, credentials_path: str | None) -> "GCSClient":
    from connectors.google_cloud_storage.gcs_client import GCSClient

    if credentials_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    return GCSClient()


def upload_sample(*, gcs_client: "GCSClient", bucket: str, object_key: str) -> None:
    from io import BytesIO

    gcs_client.upload_bytes(BytesIO(EICAR_SAMPLE.encode("utf-8")), object_key, bucket)


def delete_if_exists(*, gcs_client: "GCSClient", bucket: str, object_key: str) -> None:
    if gcs_client.key_exists(bucket, object_key):
        gcs_client.delete_object(bucket, object_key)


def get_object_metadata(*, gcs_client: "GCSClient", bucket: str, object_key: str) -> dict[str, str]:
    client = gcs_client._get_client()
    blob = client.bucket(bucket).blob(object_key)
    blob.reload()
    return {str(k): str(v) for k, v in (blob.metadata or {}).items()}


def validate_outcome(
    *,
    gcs_client: "GCSClient",
    bucket: str,
    source_key: str,
    quarantined_key: str,
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

    if gcs_client.key_exists(bucket, source_key):
        raise SystemExit(f"validation failed: source object still exists after quarantine: gs://{bucket}/{source_key}")
    if not gcs_client.key_exists(bucket, quarantined_key):
        raise SystemExit(f"validation failed: quarantined object not found: gs://{bucket}/{quarantined_key}")

    metadata: dict[str, str] = {}
    if tag_on_quarantine:
        metadata = get_object_metadata(gcs_client=gcs_client, bucket=bucket, object_key=quarantined_key)
        verdict = metadata.get("Verdict") or metadata.get("verdict")
        if verdict != "Malicious":
            raise SystemExit(
                "validation failed: expected Verdict=Malicious object metadata, "
                f"observed {json.dumps(metadata)}"
            )
    return {
        "scan_verdict": scan_result.get("verdict"),
        "remediation_result": remediation_result,
        "connector_action": connector_action,
        "quarantined_object": f"gs://{bucket}/{quarantined_key}",
        "quarantined_metadata": metadata,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate end-to-end dsx-connect-ng GCS remediation with proxy read, policy, and quarantine."
    )
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8091/api/v1")
    parser.add_argument("--connector-base-url", default="http://127.0.0.1:8630")
    parser.add_argument("--connector-name", default="google-cloud-storage-connector")
    parser.add_argument("--integration-id", default="gcs-e2e-validation")
    parser.add_argument("--scope-id", default="gcs-e2e-validation-scope")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--asset", default=None, help="bucket or bucket/prefix; used to derive bucket and root prefix when --bucket is omitted")
    parser.add_argument("--source-prefix", default="ng-e2e/scan")
    parser.add_argument("--quarantine-prefix", default="ng-e2e/quarantine")
    parser.add_argument("--sample-name", default="eicar.txt")
    parser.add_argument("--google-credentials", default=None)
    parser.add_argument("--poll-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--tag-on-quarantine", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    env_file = resolve_env_file(args.env_file)
    env_map = read_env_map(env_file)
    asset = args.asset or env_map.get("DSXCONNECTOR_ASSET") or env_map.get("ASSET") or ""
    bucket, asset_prefix_root = parse_asset(asset if not args.bucket else join_key(args.bucket, asset.partition("/")[2]))
    if args.bucket:
        bucket = args.bucket
    credentials_path = resolve_credentials_path(
        args.google_credentials or env_map.get("GOOGLE_APPLICATION_CREDENTIALS") or env_map.get("DSXCONNECTOR_GOOGLE_APPLICATION_CREDENTIALS"),
        env_file=env_file,
    )

    source_prefix = join_key(asset_prefix_root, args.source_prefix)
    quarantine_prefix = join_key(asset_prefix_root, args.quarantine_prefix)
    object_key = join_key(source_prefix, args.sample_name)
    quarantined_key = join_key(quarantine_prefix, object_key)

    gcs_client = build_gcs_client(credentials_path=credentials_path)
    delete_if_exists(gcs_client=gcs_client, bucket=bucket, object_key=object_key)
    delete_if_exists(gcs_client=gcs_client, bucket=bucket, object_key=quarantined_key)
    upload_sample(gcs_client=gcs_client, bucket=bucket, object_key=object_key)

    integration = ensure_integration(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        platform_key=asset or bucket,
        connector_base_url=args.connector_base_url,
        connector_name=args.connector_name,
    )
    scope = ensure_scope(
        api_base_url=args.api_base_url,
        scope_id=args.scope_id,
        integration_id=args.integration_id,
        resource_selector=source_prefix,
        quarantine_prefix=quarantine_prefix,
        tag_on_quarantine=args.tag_on_quarantine,
    )
    batch = submit_batch(
        api_base_url=args.api_base_url,
        integration_id=args.integration_id,
        scope_id=scope.get("scope_id") or args.scope_id,
        object_key=object_key,
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
        gcs_client=gcs_client,
        bucket=bucket,
        source_key=object_key,
        quarantined_key=quarantined_key,
        tag_on_quarantine=args.tag_on_quarantine,
        item=item,
    )

    result = {
        "integration_id": integration.get("integration_id"),
        "scope_id": scope.get("scope_id"),
        "bucket": bucket,
        "asset_prefix_root": asset_prefix_root,
        "env_file": str(env_file),
        "job_id": job_id,
        "job_state": (batch_state.get("job") or {}).get("state"),
        "job_item_id": item.get("job_item_id"),
        "item_state": item.get("state"),
        "object_key": object_key,
        "source_object": f"gs://{bucket}/{object_key}",
        "scan_stage": item.get("scan_stage"),
        "policy_stage": item.get("policy_stage"),
        "remediation_stage": item.get("remediation_stage"),
        "delivery_stage": item.get("delivery_stage"),
        **verification,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
