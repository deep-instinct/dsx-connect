#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for candidate in (REPO_ROOT, REPO_ROOT / "dsx_connect_ng"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


DEFAULT_ENV_FILE = Path.home() / ".dsx-connect-local" / "dsx-connect-ng" / ".env.local"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env_file(Path(os.environ.get("DSX_CONNECT_NG_DIRECT_ENV_FILE", str(DEFAULT_ENV_FILE))).expanduser())

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.resolver import build_scan_reader
from dsx_connect_ng.workers import scan_worker as scan_worker_module
from dsx_connect_ng.workers.scan_worker import execute_scan_via_dsxa


def list_existing_sample_files(*, sample_dir: Path, item_count: int) -> list[Path]:
    if not sample_dir.is_dir():
        raise SystemExit(f"sample directory does not exist: {sample_dir}")
    sample_paths = sorted(path for path in sample_dir.iterdir() if path.is_file())
    if len(sample_paths) < item_count:
        raise SystemExit(f"sample directory only contains {len(sample_paths)} files; requested {item_count}")
    return sample_paths[:item_count]


def build_request(*, path: Path, index: int, reader_strategy: str) -> ScanItemRequested:
    return ScanItemRequested(
        job_id="direct-ng-scan-worker-benchmark",
        job_item_id=f"direct-item-{index + 1}",
        integration_id="filesystem-local",
        object_identity=str(path),
        scan_options={
            "readerStrategy": reader_strategy,
            "path": str(path),
            "scanOnly": True,
        },
        read_hint={"path": str(path)},
    )


def scanner_metadata(request: ScanItemRequested) -> dict[str, Any]:
    metadata = request.scan_options.get("_dsx_scanner_metadata")
    return metadata if isinstance(metadata, dict) else {}


def summarize_latencies(requests: list[ScanItemRequested]) -> dict[str, dict[str, float | int | None]]:
    fields = {
        "reader_elapsed_ms": "readerElapsedMs",
        "stream_read_elapsed_ms": "streamReadElapsedMs",
        "scanner_response_wait_elapsed_ms": "scannerResponseWaitElapsedMs",
        "scanner_engine_elapsed_ms": "scannerEngineElapsedMs",
        "dsxa_elapsed_ms": "dsxaElapsedMs",
        "request_elapsed_ms": "requestElapsedMs",
    }
    summary: dict[str, dict[str, float | int | None]] = {}
    for output_key, metadata_key in fields.items():
        values = [
            float(value)
            for request in requests
            for value in [scanner_metadata(request).get(metadata_key)]
            if isinstance(value, int | float)
        ]
        if not values:
            summary[output_key] = {"count": 0, "avg_ms": None, "p95_ms": None}
            continue
        sorted_values = sorted(values)
        p95_index = min(len(sorted_values) - 1, int(len(sorted_values) * 0.95))
        summary[output_key] = {
            "count": len(values),
            "avg_ms": round(sum(values) / len(values), 3),
            "p95_ms": round(sorted_values[p95_index], 3),
        }
    return summary


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sample_dir = Path(args.sample_dir).expanduser().resolve()
    sample_paths = list_existing_sample_files(sample_dir=sample_dir, item_count=args.item_count)
    scan_worker_module._SCANNER_CLIENT_SCOPE = args.scanner_client_scope
    requests = [
        build_request(path=path, index=index, reader_strategy=args.reader_strategy)
        for index, path in enumerate(sample_paths)
    ]
    semaphore = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    completed = 0
    failed = 0
    last_progress = started

    async def scan_one(request: ScanItemRequested) -> None:
        nonlocal completed, failed, last_progress
        async with semaphore:
            reader = build_scan_reader(request, control_plane=None)
            try:
                await execute_scan_via_dsxa(request, reader)
                completed += 1
            except Exception as exc:
                failed += 1
                if not args.quiet:
                    print(
                        json.dumps(
                            {
                                "event": "direct_scan_failed",
                                "job_item_id": request.job_item_id,
                                "object_identity": request.object_identity,
                                "error": str(exc),
                            }
                        ),
                        flush=True,
                    )
            now = time.perf_counter()
            if args.progress_interval_seconds > 0 and now - last_progress >= args.progress_interval_seconds:
                last_progress = now
                terminal = completed + failed
                elapsed = now - started
                print(
                    json.dumps(
                        {
                            "event": "direct_scan_progress",
                            "terminal_items": terminal,
                            "completed_items": completed,
                            "failed_items": failed,
                            "expected_items": args.item_count,
                            "percent_complete": round((terminal / args.item_count) * 100.0, 3),
                            "elapsed_seconds": round(elapsed, 3),
                            "items_per_second": round(terminal / elapsed, 3) if elapsed else None,
                        }
                    ),
                    flush=True,
                )

    await asyncio.gather(*(scan_one(request) for request in requests))
    elapsed = time.perf_counter() - started
    await scan_worker_module.close_dsxa_client()
    return {
        "mode": "ng_scan_worker_direct",
        "reader_strategy": args.reader_strategy,
        "scanner_client_scope": args.scanner_client_scope,
        "sample_dir": str(sample_dir),
        "submitted_item_count": args.item_count,
        "completed_items": completed,
        "failed_items": failed,
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "items_per_second": round(args.item_count / elapsed, 3) if elapsed else None,
        "latency": summarize_latencies(requests),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark NG scan worker scan execution without API/Postgres/Rabbit orchestration.")
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--item-count", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--reader-strategy", choices=["native", "proxy"], default="native")
    parser.add_argument("--scanner-client-scope", choices=["shared", "per-task"], default="shared")
    parser.add_argument("--progress-interval-seconds", type=float, default=2.0)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = asyncio.run(run_benchmark(args))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
