#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TS_RE = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d{3})")
ENQUEUE_DONE_RE = re.compile(r"job\.enqueue_done job=(?P<job>[0-9a-f-]+) enqueued_total=(?P<total>\d+)")
REQUEST_STARTED_RE = re.compile(r"\[scan_request:[^\]]+\] job=(?P<job>[0-9a-f-]+|-) for .* started")
REQUEST_SUCCESS_RE = re.compile(r"\[scan_request:[^\]]+\] job=(?P<job>[0-9a-f-]+|-) success -> verdict task")
REQUEST_FAILURE_RE = re.compile(r"\[scan_request:[^\]]+\] job=(?P<job>[0-9a-f-]+|-) terminal failure \((?P<reason>[^)]+)\)")
JOB_COMPLETE_RE = re.compile(
    r"job\.terminal_complete job=(?P<job>[0-9a-f-]+) terminal=(?P<terminal>\d+) total=(?P<total>\d+) "
    r"succeeded=(?P<succeeded>\d+) failed=(?P<failed>\d+) skipped=(?P<skipped>\d+) cancelled=(?P<cancelled>\d+) "
    r"finished_at=(?P<finished_at>\d+)"
)


@dataclass
class JobStats:
    job_id: str
    first_started: dt.datetime | None = None
    last_started: dt.datetime | None = None
    enqueue_done: dt.datetime | None = None
    terminal_completed: dt.datetime | None = None
    started_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    terminal_count: int | None = None
    enqueued_total: int | None = None
    succeeded_count: int | None = None
    failed_count: int | None = None
    skipped_count: int | None = None
    cancelled_count: int | None = None


def parse_ts(line: str) -> dt.datetime | None:
    m = TS_RE.search(line)
    if not m:
        return None
    base = dt.datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
    return base.replace(microsecond=int(m.group("ms")) * 1000)


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(round(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_logs(log_dir: Path) -> dict[str, JobStats]:
    jobs: dict[str, JobStats] = {}

    def get_job(job_id: str) -> JobStats:
        stats = jobs.get(job_id)
        if stats is None:
            stats = JobStats(job_id=job_id)
            jobs[job_id] = stats
        return stats

    for log_name in ("api.log", "workers.log"):
        path = log_dir / log_name
        if not path.exists():
            continue
        for raw in path.read_text(errors="ignore").splitlines():
            line = ANSI_RE.sub("", raw)
            ts = parse_ts(line)
            if ts is None:
                continue

            m = ENQUEUE_DONE_RE.search(line)
            if m:
                stats = get_job(m.group("job"))
                stats.enqueue_done = ts
                stats.enqueued_total = int(m.group("total"))
                continue

            m = REQUEST_STARTED_RE.search(line)
            if m and m.group("job") != "-":
                stats = get_job(m.group("job"))
                stats.started_count += 1
                stats.first_started = min(filter(None, [stats.first_started, ts]), default=ts)
                stats.last_started = max(filter(None, [stats.last_started, ts]), default=ts)
                continue

            m = REQUEST_SUCCESS_RE.search(line)
            if m and m.group("job") != "-":
                stats = get_job(m.group("job"))
                stats.success_count += 1
                continue

            m = REQUEST_FAILURE_RE.search(line)
            if m and m.group("job") != "-":
                stats = get_job(m.group("job"))
                stats.failure_count += 1
                continue

            m = JOB_COMPLETE_RE.search(line)
            if m:
                stats = get_job(m.group("job"))
                stats.terminal_completed = ts
                stats.terminal_count = int(m.group("terminal"))
                stats.enqueued_total = int(m.group("total"))
                stats.succeeded_count = int(m.group("succeeded"))
                stats.failed_count = int(m.group("failed"))
                stats.skipped_count = int(m.group("skipped"))
                stats.cancelled_count = int(m.group("cancelled"))
                continue

    return jobs


def choose_jobs(jobs: dict[str, JobStats], job_id: str | None, latest: bool) -> list[JobStats]:
    items = list(jobs.values())
    if job_id:
        return [j for j in items if j.job_id == job_id]
    if latest:
        ranked = sorted(
            items,
            key=lambda j: (
                j.terminal_completed or j.enqueue_done or j.last_started or dt.datetime.min,
                j.job_id,
            ),
            reverse=True,
        )
        return ranked[:1]
    return sorted(items, key=lambda j: (j.terminal_completed or j.enqueue_done or j.last_started or dt.datetime.min, j.job_id), reverse=True)


def print_job(stats: JobStats) -> None:
    terminal_total = (
        stats.terminal_count
        if stats.terminal_count is not None
        else (stats.success_count + stats.failure_count)
    )
    start_to_enqueue = None
    if stats.first_started and stats.enqueue_done:
        start_to_enqueue = (stats.enqueue_done - stats.first_started).total_seconds()
    processing_window = None
    if stats.first_started and stats.terminal_completed:
        processing_window = (stats.terminal_completed - stats.first_started).total_seconds()
    files_per_sec = None
    if processing_window and processing_window > 0 and terminal_total:
        files_per_sec = terminal_total / processing_window

    print(f"job_id:           {stats.job_id}")
    print(f"first_started:    {stats.first_started or ''}")
    print(f"enqueue_done:     {stats.enqueue_done or ''}")
    print(f"terminal_done:    {stats.terminal_completed or ''}")
    print(f"enqueued_total:   {stats.enqueued_total if stats.enqueued_total is not None else ''}")
    print(f"started_count:    {stats.started_count}")
    print(f"terminal_count:   {terminal_total}")
    print(f"succeeded:        {stats.succeeded_count if stats.succeeded_count is not None else stats.success_count}")
    print(f"failed:           {stats.failed_count if stats.failed_count is not None else stats.failure_count}")
    print(f"skipped:          {stats.skipped_count if stats.skipped_count is not None else ''}")
    print(f"cancelled:        {stats.cancelled_count if stats.cancelled_count is not None else ''}")
    print(f"enqueue_window:   {fmt_duration(start_to_enqueue)}")
    print(f"processing_time:  {fmt_duration(processing_window)}")
    print(f"files_per_sec:    {f'{files_per_sec:.2f}' if files_per_sec is not None else ''}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze DSX-Connect local job throughput from api/worker logs.")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path.home() / ".dsx-connect-local" / "dsx-connect-desktop" / "logs",
        help="Directory containing api.log and workers.log",
    )
    parser.add_argument("--job-id", help="Specific job_id to analyze")
    parser.add_argument("--latest", action="store_true", help="Show only the latest observed job")
    args = parser.parse_args()

    jobs = parse_logs(args.log_dir)
    selected = choose_jobs(jobs, args.job_id, args.latest)
    if not selected:
        print("No matching jobs found.")
        return 1

    for stats in selected:
        print_job(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
