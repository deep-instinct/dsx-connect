#!/usr/bin/env python3
"""
Hunt for DSX/A "brain" false positives.

Phase 1 (scan):    scan a corpus through a DSXA with D-Cloud OFF so verdicts come
                   purely from the local deep-learning brain. Every result is
                   appended to a JSONL ledger (resumable; files are de-duped by sha256).
Phase 2 (recheck): take every file the brain called Malicious and submit its sha256
                   to /scan/by_hash on a DSXA with D-Cloud ON. A Benign cloud verdict
                   means the brain disagreed with D-Cloud reputation -> FP candidate.

Examples:
  # both phases, two scanners
  python scripts/find_false_positives.py run ~/corpus \
      --brain-url http://dsxa-nocloud:5000 --cloud-url http://dsxa-cloud:5000 --out ./fp_hunt

  # one scanner: scan, flip D-Cloud on, then recheck from the ledger
  python scripts/find_false_positives.py scan ~/corpus --brain-url http://dsxa:5000 --out ./fp_hunt
  python scripts/find_false_positives.py recheck --cloud-url http://dsxa:5000 --out ./fp_hunt
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from dsxa_sdk_py.client import AsyncDSXAClient

SCAN_LEDGER = "brain_scan.jsonl"
RECHECK_LEDGER = "cloud_recheck.jsonl"
FP_CSV = "false_positives.csv"


def iter_files(roots: list[str], max_bytes: int | None) -> Iterator[Path]:
    for root in roots:
        base = Path(root).expanduser()
        if base.is_file():
            candidates: Iterator[Path] = iter([base])
        else:
            candidates = (p for p in base.rglob("*") if p.is_file() and not p.is_symlink())
        for path in candidates:
            if max_bytes is not None and path.stat().st_size > max_bytes:
                continue
            yield path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize(resp: Any) -> dict[str, Any]:
    details = resp.verdict_details
    info = resp.file_info
    return {
        "verdict": resp.verdict.value,
        "reason": details.reason,
        "event_description": details.event_description,
        "threat_type": details.threat_type.value if details.threat_type else None,
        "file_type": info.file_type if info else None,
        "dsxa_file_hash": info.file_hash if info else None,
        "container_hash": info.container_hash if info else None,
        "scan_guid": resp.scan_guid,
    }


def make_client(url: str, token: str | None, timeout: float, insecure: bool) -> AsyncDSXAClient:
    return AsyncDSXAClient(base_url=url, auth_token=token, timeout=timeout, verify_tls=not insecure)


# -------- Phase 1: brain scan (D-Cloud off) --------
async def phase_scan(args: argparse.Namespace) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / SCAN_LEDGER
    prior = load_jsonl(ledger_path)
    seen_hashes = {r["sha256"] for r in prior if r.get("sha256") and "error" not in r}
    seen_paths = {r["path"] for r in prior if "error" not in r}

    max_bytes = int(args.max_mb * 1024 * 1024) if args.max_mb else None
    todo: list[Path] = []
    for p in iter_files(args.paths, max_bytes):
        if str(p) not in seen_paths:
            todo.append(p)
    print(f"[scan] {len(todo)} files to scan ({len(prior)} already in ledger)", file=sys.stderr)

    sem = asyncio.Semaphore(args.concurrency)
    counts: Counter[str] = Counter()
    done = 0
    lock = asyncio.Lock()

    async with make_client(args.brain_url, args.auth_token, args.timeout, args.insecure) as client:
        with ledger_path.open("a") as ledger:

            async def worker(path: Path) -> None:
                nonlocal done
                async with sem:
                    row: dict[str, Any] = {"path": str(path), "size": path.stat().st_size}
                    try:
                        data = await asyncio.to_thread(path.read_bytes)
                        row["sha256"] = hashlib.sha256(data).hexdigest()
                        if row["sha256"] in seen_hashes:
                            row["verdict"] = "Duplicate"
                        else:
                            seen_hashes.add(row["sha256"])
                            t0 = time.perf_counter()
                            resp = await client.scan_binary(data, custom_metadata="fp-hunt:brain")
                            row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                            row.update(summarize(resp))
                    except Exception as exc:  # keep going; errored rows are retried on resume
                        row["error"] = f"{type(exc).__name__}: {exc}"
                    async with lock:
                        ledger.write(json.dumps(row) + "\n")
                        ledger.flush()
                        counts[row.get("verdict") or "error"] += 1
                        done += 1
                        if row.get("verdict") == "Malicious":
                            print(f"  MALICIOUS {row['sha256'][:16]} {path}", file=sys.stderr)
                        if done % 50 == 0 or done == len(todo):
                            print(f"[scan] {done}/{len(todo)} {dict(counts)}", file=sys.stderr)

            await asyncio.gather(*(worker(p) for p in todo))


# -------- Phase 2: hash recheck (D-Cloud on) --------
async def phase_recheck(args: argparse.Namespace) -> None:
    out = Path(args.out)
    scans = load_jsonl(out / SCAN_LEDGER)
    malicious: dict[str, dict[str, Any]] = {}
    for r in scans:
        if r.get("verdict") == "Malicious" and r.get("sha256"):
            malicious.setdefault(r["sha256"], r)
    print(f"[recheck] {len(malicious)} unique brain-malicious hashes", file=sys.stderr)

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []

    async with make_client(args.cloud_url, args.auth_token, args.timeout, args.insecure) as client:

        async def worker(sha: str, brain: dict[str, Any]) -> None:
            async with sem:
                row: dict[str, Any] = {
                    "sha256": sha,
                    "path": brain["path"],
                    "brain_verdict": brain["verdict"],
                    "brain_threat_type": brain.get("threat_type"),
                    "brain_reason": brain.get("reason"),
                    "file_type": brain.get("file_type"),
                    "container_hash": brain.get("container_hash"),
                }
                try:
                    resp = await client.scan_hash(sha, custom_metadata="fp-hunt:cloud")
                    s = summarize(resp)
                    row["cloud_verdict"] = s["verdict"]
                    row["cloud_reason"] = s["reason"]
                    row["cloud_threat_type"] = s["threat_type"]
                except Exception as exc:
                    row["cloud_verdict"] = None
                    row["error"] = f"{type(exc).__name__}: {exc}"
                row["classification"] = {
                    "Benign": "false_positive",
                    "Malicious": "confirmed_malicious",
                }.get(row["cloud_verdict"] or "", "no_cloud_verdict" if "error" not in row else "error")
                results.append(row)

        await asyncio.gather(*(worker(sha, r) for sha, r in malicious.items()))

    with (out / RECHECK_LEDGER).open("w") as fh:
        for row in results:
            fh.write(json.dumps(row) + "\n")

    fps = [r for r in results if r["classification"] == "false_positive"]
    fields = ["sha256", "path", "file_type", "brain_threat_type", "brain_reason", "cloud_verdict", "cloud_reason", "container_hash"]
    with (out / FP_CSV).open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(fps)

    if args.copy_to:
        dest = Path(args.copy_to)
        dest.mkdir(parents=True, exist_ok=True)
        for r in fps:
            src = Path(r["path"])
            if src.exists():
                shutil.copy2(src, dest / f"{r['sha256']}{src.suffix}")

    counts = Counter(r["classification"] for r in results)
    print(f"[recheck] {dict(counts)}", file=sys.stderr)
    print(f"[recheck] false positives written to {out / FP_CSV}", file=sys.stderr)
    for r in fps:
        print(f"{r['sha256']}  {r.get('brain_threat_type') or '-':10}  {r['path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Find DSX/A brain false positives using D-Cloud hash reputation.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", default="./fp_hunt", help="Output directory for ledgers and reports")
        p.add_argument("--auth-token", default=os.getenv("DSXA_AUTH_TOKEN"))
        p.add_argument("--concurrency", type=int, default=8)
        p.add_argument("--timeout", type=float, default=120.0)
        p.add_argument("--insecure", action="store_true", help="Skip TLS verification")

    def scan_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("paths", nargs="+", help="Files or directories to scan (recursive)")
        p.add_argument("--brain-url", default=os.getenv("DSXA_BRAIN_URL", "http://localhost:5000"),
                       help="DSXA with D-Cloud disabled")
        p.add_argument("--max-mb", type=float, default=None, help="Skip files larger than this")

    def recheck_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cloud-url", default=os.getenv("DSXA_CLOUD_URL", "http://localhost:5000"),
                       help="DSXA with D-Cloud enabled")
        p.add_argument("--copy-to", default=None, help="Copy false-positive files here, named by sha256")

    p_scan = sub.add_parser("scan", help="Phase 1: brain-only scan")
    common(p_scan)
    scan_opts(p_scan)

    p_re = sub.add_parser("recheck", help="Phase 2: by_hash recheck of brain-malicious files")
    common(p_re)
    recheck_opts(p_re)

    p_run = sub.add_parser("run", help="Both phases back to back")
    common(p_run)
    scan_opts(p_run)
    recheck_opts(p_run)

    args = parser.parse_args()
    if args.cmd in ("scan", "run"):
        asyncio.run(phase_scan(args))
    if args.cmd in ("recheck", "run"):
        asyncio.run(phase_recheck(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
