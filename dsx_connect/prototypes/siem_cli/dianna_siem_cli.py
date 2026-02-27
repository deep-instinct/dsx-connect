#!/usr/bin/env python3
"""Prototype SIEM CLI for DSX-Connect DIANNA workflow.

Commands:
  - analyze-from-siem: enqueue DIANNA analysis via DSX-Connect
  - get-result:        fetch DIANNA analysis result via DSX-Connect proxy endpoint

Examples:
  python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py analyze-from-siem \
    --base-url http://127.0.0.1:8586 \
    --scan-request-task-id c136b7f7-1b68-4f99-979d-f9b36d59f54b

  python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py get-result \
    --base-url http://127.0.0.1:8586 \
    --analysis-id 150
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import requests

API_PREFIX = "/dsx-connect/api/v1"


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _api_url(base_url: str, path: str) -> str:
    return f"{_normalize_base_url(base_url)}{API_PREFIX}{path}"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_analyze_from_siem(args: argparse.Namespace) -> int:
    url = _api_url(args.base_url, "/dianna/analyze-from-siem")
    body = {
        "scan_request_task_id": args.scan_request_task_id,
        "connector_uuid": args.connector_uuid,
        "connector_url": args.connector_url,
        "location": args.location,
        "metainfo": args.metainfo,
        "archive_password": args.archive_password,
    }
    # remove unset fields
    body = {k: v for k, v in body.items() if v is not None}

    if "scan_request_task_id" not in body and not (
        ("connector_uuid" in body or "connector_url" in body) and "location" in body
    ):
        print(
            "error: provide either --scan-request-task-id OR (--connector-uuid/--connector-url and --location)",
            file=sys.stderr,
        )
        return 2

    try:
        res = requests.post(url, json=body, timeout=args.timeout)
    except requests.RequestException as e:
        print(f"request failed: {e}", file=sys.stderr)
        return 1

    try:
        payload = res.json()
    except Exception:
        payload = {"raw": res.text}

    if res.ok:
        _print_json(payload)
        return 0

    print(f"HTTP {res.status_code}", file=sys.stderr)
    _print_json(payload)
    return 1


def _fetch_result(base_url: str, analysis_id: str, timeout: float) -> tuple[int, Any]:
    url = _api_url(base_url, f"/dianna/result/{analysis_id}")
    try:
        res = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        return 0, {"error": str(e)}

    try:
        payload = res.json()
    except Exception:
        payload = {"raw": res.text}
    return res.status_code, payload


def cmd_get_result(args: argparse.Namespace) -> int:
    attempts = max(1, int(args.attempts))
    sleep_seconds = max(0.0, float(args.sleep_seconds))

    for i in range(1, attempts + 1):
        status_code, payload = _fetch_result(args.base_url, args.analysis_id, args.timeout)
        if status_code == 200:
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            st = str(result.get("status", "")).upper()
            _print_json(payload)
            if st in {"SUCCESS", "FAILED", "ERROR", "CANCELLED"}:
                return 0
            if i < attempts:
                time.sleep(sleep_seconds)
                continue
            return 0

        print(f"attempt {i}/{attempts}: HTTP {status_code}", file=sys.stderr)
        _print_json(payload)
        if i < attempts:
            time.sleep(sleep_seconds)

    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DSX-Connect DIANNA SIEM prototype CLI")
    p.add_argument("--base-url", default="http://127.0.0.1:8586", help="DSX-Connect base URL")
    p.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")

    sub = p.add_subparsers(dest="command", required=True)

    p_an = sub.add_parser("analyze-from-siem", help="enqueue DIANNA analysis")
    p_an.add_argument("--scan-request-task-id")
    p_an.add_argument("--connector-uuid")
    p_an.add_argument("--connector-url")
    p_an.add_argument("--location")
    p_an.add_argument("--metainfo")
    p_an.add_argument("--archive-password")
    p_an.set_defaults(func=cmd_analyze_from_siem)

    p_gr = sub.add_parser("get-result", help="fetch DIANNA result via DSX-Connect")
    p_gr.add_argument("--analysis-id", required=True)
    p_gr.add_argument("--attempts", type=int, default=1, help="poll attempts")
    p_gr.add_argument("--sleep-seconds", type=float, default=2.0, help="sleep between attempts")
    p_gr.set_defaults(func=cmd_get_result)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
