#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TERMINAL_JOB_STATES = {"completed", "failed", "cancelled"}
LATENCY_KEYS = (
    "reader_elapsed_ms",
    "stream_read_elapsed_ms",
    "scanner_response_wait_elapsed_ms",
    "scanner_engine_elapsed_ms",
    "dsxa_elapsed_ms",
    "request_elapsed_ms",
    "scan_stage_ms",
    "queue_wait_ms",
)


@dataclass(frozen=True)
class HttpConfig:
    api_base_url: str
    timeout_seconds: float
    insecure: bool

    @property
    def context(self):
        return ssl._create_unverified_context() if self.insecure else None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _url(base_url: str, *parts: str, query: dict[str, Any] | None = None) -> str:
    out = "/".join([base_url.rstrip("/"), *(part.strip("/") for part in parts)])
    if query:
        encoded = urlencode({key: value for key, value in query.items() if value is not None})
        if encoded:
            out = f"{out}?{encoded}"
    return out


def request_json(config: HttpConfig, method: str, url: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=config.timeout_seconds, context=config.context) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return exc.code, parsed
    except (TimeoutError, URLError) as exc:
        raise SystemExit(f"request failed: method={method} url={url} error={exc}") from exc


def require_success(status: int, payload: Any, *, action: str) -> Any:
    if status >= 400:
        raise SystemExit(f"{action} failed: status={status} payload={json.dumps(payload)}")
    return payload


def extract_job_id(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise SystemExit(f"response did not contain a job object: {json.dumps(payload)}")
    candidates = [
        payload.get("job_id"),
        (payload.get("job") or {}).get("job_id") if isinstance(payload.get("job"), dict) else None,
        payload.get("id"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise SystemExit(f"could not find job_id in response: {json.dumps(payload)}")


def start_scope_scan(
    config: HttpConfig,
    *,
    scope_id: str,
    reader_strategy: str,
    limit: int,
    extra_payload: dict[str, Any],
) -> tuple[str, Any]:
    payload = {
        "reader_strategy": reader_strategy,
        "limit": limit,
        "payload": extra_payload,
    }
    status, response = request_json(
        config,
        "POST",
        _url(config.api_base_url, "ui", "scopes", scope_id, "scan"),
        payload,
    )
    require_success(status, response, action="scope scan submit")
    return extract_job_id(response), response


def get_progress(config: HttpConfig, *, job_id: str, item_limit: int) -> dict[str, Any]:
    status, payload = request_json(
        config,
        "GET",
        _url(config.api_base_url, "execution", "jobs", job_id, "progress", query={"item_limit": item_limit}),
    )
    require_success(status, payload, action="progress fetch")
    if not isinstance(payload, dict):
        raise SystemExit(f"progress response was not an object: {json.dumps(payload)}")
    return payload


def get_items(config: HttpConfig, *, job_id: str, limit: int) -> list[dict[str, Any]]:
    status, payload = request_json(
        config,
        "GET",
        _url(config.api_base_url, "execution", "jobs", job_id, "items", query={"limit": limit}),
    )
    require_success(status, payload, action="job items fetch")
    if not isinstance(payload, list):
        raise SystemExit(f"items response was not a list: {json.dumps(payload)}")
    return [item for item in payload if isinstance(item, dict)]


def latency_pair(progress: dict[str, Any], key: str) -> str:
    latency = progress.get("latency") if isinstance(progress.get("latency"), dict) else {}
    summary = latency.get(key) if isinstance(latency.get(key), dict) else {}
    avg = summary.get("avg_ms")
    p95 = summary.get("p95_ms")
    if avg is None and p95 is None:
        return ""
    return f"{avg or ''}/{p95 or ''}"


def summarize_progress(progress: dict[str, Any]) -> dict[str, Any]:
    throughput = progress.get("throughput") if isinstance(progress.get("throughput"), dict) else {}
    total_window = throughput.get("total") if isinstance(throughput.get("total"), dict) else {}
    summary = progress.get("item_summary") if isinstance(progress.get("item_summary"), dict) else {}
    return {
        "job_id": progress.get("job_id"),
        "state": progress.get("state"),
        "total_items": progress.get("total_items"),
        "terminal_items": progress.get("terminal_items"),
        "completed_items": summary.get("completed"),
        "failed_items": summary.get("failed"),
        "cancelled_items": summary.get("cancelled"),
        "elapsed_seconds": progress.get("elapsed_seconds"),
        "items_per_second": total_window.get("items_per_second"),
        "latency": progress.get("latency"),
        "backlog": progress.get("backlog"),
        "runtime": progress.get("runtime"),
        "bottleneck_hints": progress.get("bottleneck_hints"),
        "derived_from_item_count": progress.get("derived_from_item_count"),
        "derived_from_item_limit": progress.get("derived_from_item_limit"),
    }


def item_metadata_sample(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for item in items:
        scan_stage = item.get("scan_stage") if isinstance(item.get("scan_stage"), dict) else {}
        metadata = scan_stage.get("metadata") if isinstance(scan_stage.get("metadata"), dict) else {}
        if metadata:
            sampled.append(
                {
                    "object_identity": item.get("object_identity"),
                    "state": item.get("state"),
                    "scan_state": scan_stage.get("state"),
                    "metadata": metadata,
                }
            )
    return sampled


def print_progress_event(progress: dict[str, Any]) -> None:
    event = summarize_progress(progress)
    event["event"] = "benchmark_progress"
    event["observed_at"] = utc_now_iso()
    print(json.dumps(event), flush=True)


def poll_until_done(
    config: HttpConfig,
    *,
    job_id: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
    item_limit: int,
) -> list[dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    samples: list[dict[str, Any]] = []
    while True:
        progress = get_progress(config, job_id=job_id, item_limit=item_limit)
        samples.append(progress)
        print_progress_event(progress)

        total = int(progress.get("total_items") or 0)
        terminal = int(progress.get("terminal_items") or 0)
        state = str(progress.get("state") or "")
        if total > 0 and terminal >= total:
            return samples
        if state in TERMINAL_JOB_STATES:
            return samples
        if time.time() >= deadline:
            raise SystemExit(f"timed out waiting for job {job_id}; last_progress={json.dumps(progress)}")
        time.sleep(poll_interval_seconds)


def markdown_row(label: str, mode: str, progress: dict[str, Any], notes: str) -> str:
    total = progress.get("total_items") or ""
    elapsed = progress.get("elapsed_seconds") or ""
    throughput = (
        (progress.get("throughput") or {}).get("total", {}).get("items_per_second")
        if isinstance(progress.get("throughput"), dict)
        else None
    )
    summary = progress.get("item_summary") if isinstance(progress.get("item_summary"), dict) else {}
    failures = int(summary.get("failed") or 0) + int(summary.get("cancelled") or 0)
    return (
        f"| {label} | {mode} | `{total}` | `{elapsed}` | `{throughput or ''}` | `{failures}` | "
        f"`{latency_pair(progress, 'reader_elapsed_ms')}` | "
        f"`{latency_pair(progress, 'stream_read_elapsed_ms')}` | "
        f"`{latency_pair(progress, 'dsxa_elapsed_ms')}` | "
        f"`{latency_pair(progress, 'scanner_engine_elapsed_ms')}` | {notes} |"
    )


def parse_json_object(raw: str | None, *, arg_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{arg_name} must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{arg_name} must decode to a JSON object")
    return payload


def write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a DSX-Connect 2 job or protected-scope scan.")
    parser.add_argument("--api-base-url", required=True, help="Base API URL, for example https://host/api/v1")
    parser.add_argument("--label", default="2G benchmark")
    parser.add_argument("--mode", default="2g-protected-scope")
    parser.add_argument("--job-id", help="Existing job ID to observe instead of starting a new scan")
    parser.add_argument("--scope-id", help="Protected scope ID to scan when --job-id is omitted")
    parser.add_argument("--reader-strategy", default="proxy")
    parser.add_argument("--limit", type=int, default=1000, help="Scope scan enumeration limit")
    parser.add_argument("--payload-json", default="{}", help="Extra payload object for scope scan requests")
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--progress-item-limit", type=int, default=1000)
    parser.add_argument("--sample-items-limit", type=int, default=100)
    parser.add_argument("--notes", default="")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for lab self-signed certs")
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = HttpConfig(
        api_base_url=args.api_base_url,
        timeout_seconds=args.request_timeout_seconds,
        insecure=args.insecure,
    )
    submit_response = None
    if args.job_id:
        job_id = args.job_id
        started_by_script = False
    else:
        if not args.scope_id:
            raise SystemExit("provide either --job-id or --scope-id")
        job_id, submit_response = start_scope_scan(
            config,
            scope_id=args.scope_id,
            reader_strategy=args.reader_strategy,
            limit=args.limit,
            extra_payload=parse_json_object(args.payload_json, arg_name="--payload-json"),
        )
        started_by_script = True
        print(json.dumps({"event": "benchmark_job_started", "job_id": job_id, "response": submit_response}), flush=True)

    samples = poll_until_done(
        config,
        job_id=job_id,
        poll_interval_seconds=args.poll_interval_seconds,
        timeout_seconds=args.timeout_seconds,
        item_limit=args.progress_item_limit,
    )
    final_progress = samples[-1]
    items = get_items(config, job_id=job_id, limit=args.sample_items_limit) if args.sample_items_limit > 0 else []
    result = {
        "label": args.label,
        "mode": args.mode,
        "job_id": job_id,
        "started_by_script": started_by_script,
        "submit_response": submit_response,
        "final": summarize_progress(final_progress),
        "progress_samples": [summarize_progress(sample) for sample in samples],
        "item_metadata_sample": item_metadata_sample(items),
        "markdown_header": (
            "| Label | Mode | Items | Elapsed sec | Items/sec | Failures | "
            "Reader avg/p95 ms | Stream avg/p95 ms | DSXA avg/p95 ms | Engine avg/p95 ms | Notes |"
        ),
        "markdown_separator": "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        "markdown_row": markdown_row(args.label, args.mode, final_progress, args.notes),
    }
    if args.output_json:
        write_output(args.output_json, result)
    print(json.dumps({"event": "benchmark_result", **result}, indent=2), flush=True)
    print(result["markdown_header"])
    print(result["markdown_separator"])
    print(result["markdown_row"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
