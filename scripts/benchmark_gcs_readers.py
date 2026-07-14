#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MiB = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str
    size: int | None = None


@dataclass(frozen=True)
class ReadMeasurement:
    mode: str
    bucket: str
    key: str
    size: int | None
    bytes_read: int
    elapsed_ms: float
    error: str | None = None


@dataclass(frozen=True)
class ReadContext:
    gcs_sdk_client: Any | None = None
    gcs_connector_client: Any | None = None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def _summary(mode: str, measurements: list[ReadMeasurement], elapsed_seconds: float) -> dict[str, Any]:
    successful = [item for item in measurements if item.error is None]
    failed = [item for item in measurements if item.error is not None]
    elapsed_values = [item.elapsed_ms for item in successful]
    bytes_read = sum(item.bytes_read for item in successful)
    return {
        "mode": mode,
        "items": len(measurements),
        "successful_items": len(successful),
        "failed_items": len(failed),
        "bytes_read": bytes_read,
        "mib_read": round(bytes_read / MiB, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "items_per_second": round(len(successful) / elapsed_seconds, 3) if elapsed_seconds > 0 else None,
        "mib_per_second": round((bytes_read / MiB) / elapsed_seconds, 3) if elapsed_seconds > 0 else None,
        "read_elapsed_ms": {
            "avg": round(statistics.fmean(elapsed_values), 3) if elapsed_values else None,
            "p50": round(_percentile(elapsed_values, 0.50), 3) if elapsed_values else None,
            "p95": round(_percentile(elapsed_values, 0.95), 3) if elapsed_values else None,
            "max": round(max(elapsed_values), 3) if elapsed_values else None,
        },
        "errors": [
            {
                "bucket": item.bucket,
                "key": item.key,
                "error": item.error,
            }
            for item in failed[:10]
        ],
    }


def _load_objects_from_json(path: Path) -> list[ObjectRef]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("--object-json must contain a JSON array")
    refs: list[ObjectRef] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise SystemExit(f"--object-json item {index} is not an object")
        bucket = str(item.get("bucket") or "").strip()
        key = str(item.get("key") or item.get("name") or item.get("path") or "").strip().strip("/")
        if not bucket or not key:
            raise SystemExit(f"--object-json item {index} requires bucket and key/path")
        size = item.get("size")
        refs.append(ObjectRef(bucket=bucket, key=key, size=size if isinstance(size, int) else None))
    return refs


def _list_gcs_objects(bucket: str, prefix: str, *, limit: int) -> list[ObjectRef]:
    try:
        from google.cloud import storage
    except Exception as exc:
        raise SystemExit("google-cloud-storage is required for --bucket/--prefix listing") from exc
    client = storage.Client()
    refs: list[ObjectRef] = []
    for blob in client.list_blobs(bucket, prefix=prefix.strip("/")):
        if blob.name.endswith("/"):
            continue
        refs.append(ObjectRef(bucket=bucket, key=blob.name, size=blob.size))
        if len(refs) >= limit:
            break
    return refs


def _native_read_sync(ref: ObjectRef, *, chunk_size: int) -> int:
    from google.cloud import storage

    return _gcs_sdk_read_sync(ref, client=storage.Client(), chunk_size=chunk_size)


async def _dsx_native_read(ref: ObjectRef, *, chunk_size: int) -> int:
    from dsx_connect_ng.jobs.contracts import ScanItemRequested
    from dsx_connect_ng.jobs.models import ContentSource
    from dsx_connect_ng.readers.gcs_native import GCSNativeReader

    request = ScanItemRequested(
        job_id="gcs-reader-benchmark",
        job_item_id=f"gcs-reader-benchmark:{ref.bucket}/{ref.key}",
        integration_id="gcs-reader-benchmark",
        object_identity=f"{ref.bucket}/{ref.key}",
        content_source=ContentSource(mode="original", locator=ref.key),
        read_hint={"path": ref.key, "sizeInBytes": ref.size},
        scan_options={"bucket": ref.bucket, "path": ref.key},
    )
    reader = GCSNativeReader(chunk_size=chunk_size)
    result = await reader.acquire(request)
    total = 0
    if result.content_stream is None:
        return 0
    async for chunk in result.content_stream:
        total += len(chunk)
    return total


def _gcs_sdk_read_sync(ref: ObjectRef, *, client: Any, chunk_size: int) -> int:
    blob = client.bucket(ref.bucket).blob(ref.key)
    total = 0
    with blob.open("rb", chunk_size=chunk_size) as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
    return total


def _gcs_client_stream_read_sync(ref: ObjectRef, *, client: Any, chunk_size: int) -> int:
    total = 0
    with client.open_object_stream(ref.bucket, ref.key) as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
    return total


def _gcs_client_buffer_read_sync(ref: ObjectRef, *, client: Any, chunk_size: int) -> int:
    content = client.get_object(ref.bucket, ref.key)
    total = 0
    while True:
        chunk = content.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
    return total


def _proxy_read_sync(ref: ObjectRef, *, endpoint_url: str, timeout_seconds: float, chunk_size: int) -> int:
    payload = {
        "location": ref.key,
        "metainfo": f"{ref.bucket}/{ref.key}",
        "connector_url": endpoint_url.rsplit("/", 1)[0],
        "size_in_bytes": ref.size,
        "scan_job_id": "gcs-reader-benchmark",
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        endpoint_url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/octet-stream, application/json"},
        method="POST",
    )
    total = 0
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raw = response.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"connector returned JSON: {raw[:500]}")
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"http {exc.code}: {raw[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"transport failure: {exc}") from exc
    return total


async def _dsx_proxy_read(ref: ObjectRef, *, endpoint_url: str, timeout_seconds: float, chunk_size: int) -> int:
    from dsx_connect_ng.jobs.models import ContentSource
    from dsx_connect_ng.readers.contracts import ConnectorProxyReadRequest
    from dsx_connect_ng.readers.proxy import ConnectorProxyRuntimeConfig, http_connector_proxy_stream

    request = ConnectorProxyReadRequest(
        job_id="gcs-reader-benchmark",
        job_item_id=f"gcs-reader-benchmark:{ref.bucket}/{ref.key}",
        integration_id="gcs-reader-benchmark",
        object_identity=f"{ref.bucket}/{ref.key}",
        content_source=ContentSource(mode="original", locator=ref.key),
        read_hint={
            "location": ref.key,
            "metainfo": f"{ref.bucket}/{ref.key}",
            "sizeInBytes": ref.size,
        },
    )
    config = ConnectorProxyRuntimeConfig(
        endpoint_url=endpoint_url,
        auth_mode="none",
        timeout_seconds=timeout_seconds,
    )
    result = await http_connector_proxy_stream(request, config, chunk_size=chunk_size)
    total = 0
    if result.content_stream is None:
        return 0
    async for chunk in result.content_stream:
        total += len(chunk)
    return total


async def _measure_one(
    mode: str,
    ref: ObjectRef,
    *,
    context: ReadContext,
    proxy_endpoint: str | None,
    timeout_seconds: float,
    chunk_size: int,
) -> ReadMeasurement:
    started = time.perf_counter()
    try:
        if mode == "native":
            bytes_read = await _dsx_native_read(ref, chunk_size=chunk_size)
        elif mode == "gcs-sdk-per-read":
            bytes_read = await asyncio.to_thread(_native_read_sync, ref, chunk_size=chunk_size)
        elif mode == "gcs-sdk-shared":
            if context.gcs_sdk_client is None:
                raise RuntimeError("gcs-sdk-shared mode requires a shared SDK client")
            bytes_read = await asyncio.to_thread(
                _gcs_sdk_read_sync,
                ref,
                client=context.gcs_sdk_client,
                chunk_size=chunk_size,
            )
        elif mode == "gcs-client-stream":
            if context.gcs_connector_client is None:
                raise RuntimeError("gcs-client-stream mode requires a shared GCSClient")
            bytes_read = await asyncio.to_thread(
                _gcs_client_stream_read_sync,
                ref,
                client=context.gcs_connector_client,
                chunk_size=chunk_size,
            )
        elif mode == "gcs-client-buffer":
            if context.gcs_connector_client is None:
                raise RuntimeError("gcs-client-buffer mode requires a shared GCSClient")
            bytes_read = await asyncio.to_thread(
                _gcs_client_buffer_read_sync,
                ref,
                client=context.gcs_connector_client,
                chunk_size=chunk_size,
            )
        elif mode == "proxy":
            if proxy_endpoint is None:
                raise RuntimeError("--proxy-endpoint is required for proxy mode")
            bytes_read = await _dsx_proxy_read(
                ref,
                endpoint_url=proxy_endpoint,
                timeout_seconds=timeout_seconds,
                chunk_size=chunk_size,
            )
        elif mode == "proxy-urllib":
            if proxy_endpoint is None:
                raise RuntimeError("--proxy-endpoint is required for proxy-urllib mode")
            bytes_read = await asyncio.to_thread(
                _proxy_read_sync,
                ref,
                endpoint_url=proxy_endpoint,
                timeout_seconds=timeout_seconds,
                chunk_size=chunk_size,
            )
        else:
            raise RuntimeError(f"unsupported mode: {mode}")
        error = None
    except Exception as exc:
        bytes_read = 0
        error = f"{exc.__class__.__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return ReadMeasurement(
        mode=mode,
        bucket=ref.bucket,
        key=ref.key,
        size=ref.size,
        bytes_read=bytes_read,
        elapsed_ms=elapsed_ms,
        error=error,
    )


async def _run_mode(
    mode: str,
    objects: list[ObjectRef],
    *,
    concurrency: int,
    proxy_endpoint: str | None,
    timeout_seconds: float,
    chunk_size: int,
) -> tuple[list[ReadMeasurement], float]:
    semaphore = asyncio.Semaphore(concurrency)
    context = _build_read_context(mode)

    async def bounded(ref: ObjectRef) -> ReadMeasurement:
        async with semaphore:
            return await _measure_one(
                mode,
                ref,
                context=context,
                proxy_endpoint=proxy_endpoint,
                timeout_seconds=timeout_seconds,
                chunk_size=chunk_size,
            )

    started = time.perf_counter()
    results = await asyncio.gather(*(bounded(ref) for ref in objects))
    return results, time.perf_counter() - started


def _build_read_context(mode: str) -> ReadContext:
    if mode == "gcs-sdk-shared":
        from google.cloud import storage

        return ReadContext(gcs_sdk_client=storage.Client())
    if mode in {"gcs-client-stream", "gcs-client-buffer"}:
        from connectors.google_cloud_storage.gcs_client import GCSClient

        return ReadContext(gcs_connector_client=GCSClient())
    return ReadContext()


def _markdown_row(summary: dict[str, Any]) -> str:
    latency = summary["read_elapsed_ms"]
    return (
        f"| {summary['mode']} | `{summary['successful_items']}/{summary['items']}` | "
        f"`{summary['mib_read']}` | `{summary['elapsed_seconds']}` | "
        f"`{summary['items_per_second']}` | `{summary['mib_per_second']}` | "
        f"`{latency['avg']}` | `{latency['p95']}` |"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark DSX-Connect GCS native vs connector-proxy read throughput.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--object-json", type=Path, help="JSON array of {bucket,key,size?} objects to read.")
    source.add_argument("--bucket", help="GCS bucket to list.")
    parser.add_argument("--prefix", default="", help="GCS prefix used with --bucket.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum objects to benchmark.")
    parser.add_argument(
        "--mode",
        choices=[
            "native",
            "proxy",
            "proxy-urllib",
            "gcs-sdk-per-read",
            "gcs-sdk-shared",
            "gcs-client-stream",
            "gcs-client-buffer",
            "both",
            "raw",
            "all",
        ],
        default="both",
    )
    parser.add_argument("--proxy-endpoint", help="Connector read_file endpoint for proxy mode.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--chunk-size", type=int, default=MiB)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.object_json:
        objects = _load_objects_from_json(args.object_json)[: args.limit]
    else:
        objects = _list_gcs_objects(args.bucket, args.prefix, limit=args.limit)
    if not objects:
        raise SystemExit("no objects selected for benchmark")

    if args.mode == "both":
        modes = ["native", "proxy"]
    elif args.mode == "raw":
        modes = ["gcs-sdk-per-read", "gcs-sdk-shared", "gcs-client-stream", "gcs-client-buffer"]
    elif args.mode == "all":
        modes = ["native", "proxy", "proxy-urllib", "gcs-sdk-per-read", "gcs-sdk-shared", "gcs-client-stream", "gcs-client-buffer"]
    else:
        modes = [args.mode]
    if "proxy" in modes and not args.proxy_endpoint:
        raise SystemExit("--proxy-endpoint is required when --mode includes proxy")

    output: dict[str, Any] = {
        "object_count": len(objects),
        "total_declared_bytes": sum(ref.size or 0 for ref in objects),
        "total_declared_mib": round(sum(ref.size or 0 for ref in objects) / MiB, 3),
        "concurrency": args.concurrency,
        "chunk_size": args.chunk_size,
        "summaries": {},
    }
    for mode in modes:
        measurements, elapsed_seconds = asyncio.run(
            _run_mode(
                mode,
                objects,
                concurrency=args.concurrency,
                proxy_endpoint=args.proxy_endpoint,
                timeout_seconds=args.timeout_seconds,
                chunk_size=args.chunk_size,
            )
        )
        output["summaries"][mode] = _summary(mode, measurements, elapsed_seconds)
        print(json.dumps({"event": "gcs_reader_benchmark_mode_complete", **output["summaries"][mode]}), flush=True)

    output["markdown_header"] = "| Mode | Success | MiB Read | Elapsed sec | Items/sec | MiB/sec | Avg Read ms | P95 Read ms |"
    output["markdown_separator"] = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    output["markdown_rows"] = [_markdown_row(output["summaries"][mode]) for mode in modes]
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"event": "gcs_reader_benchmark_result", **output}, indent=2), flush=True)
    print(output["markdown_header"])
    print(output["markdown_separator"])
    for row in output["markdown_rows"]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
