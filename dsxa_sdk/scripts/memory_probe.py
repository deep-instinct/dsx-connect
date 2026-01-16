#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import threading
import time
import resource

from dsxa_sdk import DSXAClient


def iter_file_chunks(path: str, chunk_size: int) -> bytes:
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


def monitor_rss(stop_event: threading.Event, samples: list[int]) -> None:
    try:
        import psutil  # optional
    except Exception:
        return
    proc = psutil.Process(os.getpid())
    while not stop_event.is_set():
        try:
            samples.append(proc.memory_info().rss)
        except Exception:
            pass
        time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare DSXA streaming vs in-memory uploads.")
    parser.add_argument("file", help="Path to file to scan")
    parser.add_argument("mode", choices=("stream", "bytes"), help="Upload mode")
    parser.add_argument("--base-url", default=os.getenv("DSXA_BASE_URL", "http://localhost:15000"))
    parser.add_argument("--auth-token", default=os.getenv("DSXA_AUTH_TOKEN"))
    parser.add_argument("--chunk-size", type=int, default=1024 * 1024)
    args = parser.parse_args()

    samples: list[int] = []
    stop = threading.Event()
    t = threading.Thread(target=monitor_rss, args=(stop, samples), daemon=True)
    t.start()

    client = DSXAClient(base_url=args.base_url, auth_token=args.auth_token)
    prep_start = time.perf_counter()
    if args.mode == "stream":
        prep_elapsed = time.perf_counter() - prep_start
        request_start = time.perf_counter()
        resp = client.scan_binary_stream(iter_file_chunks(args.file, args.chunk_size))
    else:
        with open(args.file, "rb") as fh:
            data = fh.read()
        prep_elapsed = time.perf_counter() - prep_start
        request_start = time.perf_counter()
        resp = client.scan_binary(data)
    request_elapsed = time.perf_counter() - request_start
    elapsed = prep_elapsed + request_elapsed
    client.close()

    stop.set()
    t.join(timeout=0.2)

    # ru_maxrss units are platform-specific: bytes on macOS, KB on Linux.
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_sample = max(samples) if samples else None

    print(f"verdict={getattr(resp, 'verdict', None)}")
    print(f"prep_seconds={prep_elapsed:.3f}")
    verdict_scan_us = getattr(resp, "scan_duration_in_microseconds", None)
    verdict_scan_seconds = None
    if verdict_scan_us is not None:
        try:
            verdict_scan_seconds = float(verdict_scan_us) / 1_000_000
        except Exception:
            verdict_scan_seconds = None
    if verdict_scan_seconds is not None:
        print(f"scan_seconds={verdict_scan_seconds:.6f}")
    else:
        print("scan_seconds=unknown")
    print(f"request_seconds={request_elapsed:.3f}")
    print(f"elapsed_seconds={elapsed:.3f}")
    print(f"ru_maxrss={max_rss}")
    if peak_sample is not None:
        print(f"peak_rss_bytes={peak_sample}")
    else:
        print("peak_rss_bytes=psutil_not_installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
