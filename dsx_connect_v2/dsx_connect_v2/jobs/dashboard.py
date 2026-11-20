"""Historical file activity, job activity, and timing from persisted records."""
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from statistics import median
from threading import Lock
from time import monotonic


def _latency_summary(samples, *, include_tail=False):
    ordered = sorted(samples)
    summary = {"samples": len(ordered), "median_seconds": median(ordered) if ordered else None,
            "p95_seconds": ordered[ceil(len(ordered) * .95) - 1] if ordered else None}
    if include_tail:
        summary.update(p99_seconds=ordered[ceil(len(ordered) * .99) - 1] if ordered else None,
                       max_seconds=ordered[-1] if ordered else None)
    return summary


def _duration_seconds(value, units_per_second):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0:
        return value / units_per_second
    return None


def scan_worker_history(repo, days: int, now: datetime | None = None, *, integration_id: str | None = None):
    return scan_timing_history(repo, days, now, integration_id=integration_id, metric="scan_worker")


def scan_timing_history(repo, days: int, now: datetime | None = None, *, integration_id: str | None = None, metric: str):
    now = now or datetime.now(timezone.utc)
    hourly = days == 1
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    end_bucket = now.replace(minute=0, second=0, microsecond=0) if hourly else now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = 24 if hourly else days
    start = end_bucket - step * (count - 1)
    bucket = "hour" if hourly else "day"
    summaries = {row["at"]: {key: row[key] for key in ("samples", "median_seconds", "p95_seconds", "p99_seconds", "max_seconds")}
                 for row in repo.scan_timing_summary(start, now, integration_id, bucket, metric)}
    empty = _latency_summary([], include_tail=True)
    return {"start": start.isoformat(), "end": now.isoformat(), "bucket": bucket,
            metric: summaries.get(None, empty),
            "series": [{"at": (start + step * i).isoformat(), **summaries.get(start + step * i, empty)}
                       for i in range(count)]}



class DashboardHistoryCache:
    """Share recent history snapshots across requests to one API process."""

    def __init__(self, ttl_seconds=15, max_entries=32):
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries = OrderedDict()
        self._lock = Lock()

    def get(self, repo, days, integration_id):
        key = (repo, days, integration_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and monotonic() < entry[0]:
                self._entries.move_to_end(key)
                return entry[1]
            history = dashboard_history(repo, days, integration_id=integration_id)
            self._entries[key] = (monotonic() + self._ttl_seconds, history)
            self._entries.move_to_end(key)
            if len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return history


MINIMUM_SUSTAINED_WAIT_SECONDS = 30


def _throughput_under_load(queue_changes, completions, bucket_starts, now):
    # Use equal bucket lengths in both windows, including the final partial bucket.
    window_length = now - bucket_starts[0]
    previous_starts = [at - window_length for at in bucket_starts if at < now]
    starts = set(previous_starts + bucket_starts)
    waiting = 0
    bucket = None
    run_start = None
    run_scans = 0
    elapsed = Counter()
    scans = Counter()

    def record_run(end):
        seconds = (end - run_start).total_seconds()
        if seconds >= MINIMUM_SUSTAINED_WAIT_SECONDS:
            elapsed[bucket] += seconds
            scans[bucket] += run_scans

    # A run ends when the queue empties or its reporting bucket ends.
    times = sorted(queue_changes.keys() | completions.keys() | starts | {now})
    for at in times:
        if at == now:
            if run_start is not None:
                if now not in starts:
                    run_scans += completions[now]
                record_run(now)
            break
        waiting += queue_changes[at]
        if run_start is not None and (at in starts or waiting <= 0):
            record_run(at)
            run_start = None
        if at in starts:
            bucket = at
        if waiting > 0:
            if run_start is None:
                run_start = at
                run_scans = 0
            run_scans += completions[at]

    def summary(starts):
        count = sum(scans[at] for at in starts)
        seconds = sum(elapsed[at] for at in starts)
        return {"files_per_second": count / seconds if seconds else None,
                "scans": count, "waiting_seconds": seconds}

    series = [scans[at] / elapsed[at] if elapsed[at] else None for at in bucket_starts]
    return {"current": summary(bucket_starts), "previous": summary(previous_starts)}, series


def dashboard_history(repo, days: int, now: datetime | None = None, *,
                      integration_id: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    hourly = days == 1
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    end_bucket = now.replace(minute=0, second=0, microsecond=0) if hourly else now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = 24 if hourly else days
    start = end_bucket - step * (count - 1)
    previous_start = start - (now - start)
    bucket_starts = [start + step * i for i in range(count)]
    buckets = [{"at": at.isoformat(), "total": 0, "benign": 0, "malicious": 0, "suspicious": 0, "other": 0} for at in bucket_starts]
    quarantine = {"malicious": 0, "suspicious": 0, "file_type_policy": 0, "other": 0}
    blocked = 0
    types = {}

    backlog_changes = [0] * (count + 1)
    latency_samples = [[] for _ in buckets]
    latency_all = []
    timing_samples = {key: [[] for _ in buckets] for key in ("scan_worker", "dsxa", "job_duration")}
    job_counts = [Counter() for _ in buckets]
    queue_changes = Counter()
    scan_completions = Counter()
    connector_counts = Counter()
    connector_bucket_counts = defaultdict(Counter)
    connector_queue_changes = defaultdict(Counter)
    connector_completions = defaultdict(Counter)

    def timestamp(raw):
        if not raw:
            return None
        return raw if isinstance(raw, datetime) else datetime.fromisoformat(raw.replace("Z", "+00:00"))

    def in_window(stage):
        raw = stage.get("completed_at")
        if not raw:
            return None
        at = timestamp(raw)
        return at if start <= at <= now else None

    for row in repo.dashboard_stages(previous_start, integration_id):
        created = timestamp(row.get("created_at"))
        completed = timestamp(row.get("completed_at"))
        # Reconstruct unfinished work at each bucket's end; the current bucket ends now.
        if created and created <= now:
            first = max(0, int((created - start) // step))
            last = min(count, max(0, int((completed - start) // step))) if completed else count
            if first < last:
                backlog_changes[first] += 1
                backlog_changes[last] -= 1
            if row.get("state") == "completed" and completed and start <= completed <= now and completed >= created:
                seconds = (completed - created).total_seconds()
                latency_samples[int((completed - start) // step)].append(seconds)
                latency_all.append(seconds)
        scan = row.get("scan_stage") or {}
        policy = row.get("policy_stage") or {}
        remediation = row.get("remediation_stage") or {}
        result = scan.get("result") or {}
        verdict = str(result.get("verdict") or "").lower()
        metadata = scan.get("metadata") or {}
        connector_id = row.get("integration_id") if integration_id is None else None
        scan_started = timestamp(metadata.get("workerStartedAt") or scan.get("started_at"))
        scan_completed = timestamp(metadata.get("workerFinishedAt") or scan.get("completed_at"))
        if created and scan_started:
            waiting_start = max(created, previous_start)
            waiting_end = min(scan_started, now)
            if waiting_start < waiting_end:
                queue_changes[waiting_start] += 1
                queue_changes[waiting_end] -= 1
                if connector_id and waiting_end > start:
                    connector_queue_changes[connector_id][max(waiting_start, start)] += 1
                    connector_queue_changes[connector_id][waiting_end] -= 1
        if scan.get("state") == "completed" and scan_completed and previous_start <= scan_completed <= now:
            scan_completions[scan_completed] += 1
            if connector_id and scan_completed >= start:
                connector_completions[connector_id][scan_completed] += 1
        at = in_window(scan)
        if scan.get("state") == "completed" and at:
            index = int((at - start) / step)
            bucket = buckets[index]
            bucket["total"] += 1
            if connector_id:
                connector_counts[connector_id] += 1
                connector_bucket_counts[connector_id][index] += 1
            worker_seconds = _duration_seconds(metadata.get("workerElapsedMs"), 1000)
            if worker_seconds is None:
                worker_seconds = _duration_seconds(metadata.get("requestElapsedMs"), 1000)
            dsxa_seconds = _duration_seconds(result.get("scan_duration_in_microseconds"), 1_000_000)
            if dsxa_seconds is None:
                dsxa_seconds = _duration_seconds(metadata.get("scannerEngineElapsedMs"), 1000)
            for key, seconds in (("scan_worker", worker_seconds), ("dsxa", dsxa_seconds)):
                if seconds is not None:
                    timing_samples[key][index].append(seconds)
            key = "benign" if verdict in {"benign", "clean"} else verdict if verdict in {"malicious", "suspicious"} else "other"
            bucket[key] += 1
            file_info = result.get("file_info") or result.get("fileInfo") or {}
            file_type = str(file_info.get("file_type") or file_info.get("fileType") or result.get("fileType") or result.get("file_type") or "Unknown")
            types[file_type] = types.get(file_type, 0) + 1
        policy_result = policy.get("result") or {}
        policy_result = policy_result.get("policy_stage_result") or policy_result
        trace = policy_result.get("decision_trace") or policy_result.get("decisionTrace") or {}
        type_block = str(trace.get("policy_reason") or "").startswith("blocked_file_type:")
        if policy.get("state") == "completed" and in_window(policy) and type_block:
            blocked += 1
        action = remediation.get("result") or {}
        if remediation.get("state") == "completed" and in_window(remediation) and action.get("action") == "quarantine" and action.get("outcome") == "succeeded":
            reason = "file_type_policy" if type_block else verdict if verdict in {"malicious", "suspicious"} else "other"
            quarantine[reason] += 1

    for job in repo.dashboard_jobs(start, now, integration_id):
        if job.state not in {"completed", "failed", "cancelled"}:
            continue
        index = int((job.completed_at - start) / step)
        job_counts[index][job.state] += 1
        if job.state == "completed" and job.completed_at >= job.created_at:
            timing_samples["job_duration"][index].append((job.completed_at - job.created_at).total_seconds())

    backlog = 0
    for i, bucket in enumerate(buckets):
        backlog += backlog_changes[i]
        elapsed_minutes = (min(start + step * (i + 1), now) - (start + step * i)).total_seconds() / 60
        bucket.update(throughput_per_minute=bucket["total"] / elapsed_minutes if elapsed_minutes > 0 else 0,
                      backlog=backlog, **_latency_summary(latency_samples[i]))
        for key, samples in timing_samples.items():
            bucket[key] = _latency_summary(samples[i])
        for state in ("completed", "failed", "cancelled"):
            bucket[f"jobs_{state}"] = job_counts[i][state]
    under_load, aggregate_series = _throughput_under_load(queue_changes, scan_completions, bucket_starts, now)
    if integration_id is not None:
        throughput_series = [{"integration_id": integration_id, "files_per_second": aggregate_series,
                              "completed_scans": [bucket["total"] for bucket in buckets]}]
    else:
        throughput_series = [
            {"integration_id": connector_id, "files_per_second": _throughput_under_load(
                connector_queue_changes[connector_id], connector_completions[connector_id], bucket_starts, now)[1],
             "completed_scans": [connector_bucket_counts[connector_id][i] for i in range(count)]}
            for connector_id in sorted(connector_counts, key=lambda key: (-connector_counts[key], key))[:5]
        ]
    return {"days": days, "timezone": "UTC", "start": start.isoformat(), "end": now.isoformat(),
            "bucket": "hour" if hourly else "day", "series": buckets,
            "throughput_per_minute": sum(b["total"] for b in buckets) / max((now - start).total_seconds() / 60, 1 / 60),
            "backlog": backlog, "latency": _latency_summary(latency_all),
            "under_load": under_load, "under_load_series": throughput_series,
            "minimum_sustained_wait_seconds": MINIMUM_SUSTAINED_WAIT_SECONDS,
            "jobs": {state: sum(counts[state] for counts in job_counts) for state in ("completed", "failed", "cancelled")},
            **{key: _latency_summary([value for bucket in samples for value in bucket])
               for key, samples in timing_samples.items()},
            "total_scans": sum(b["total"] for b in buckets), "quarantined": quarantine,
            "file_type_policy_matches": blocked,
            "file_types": [{"type": key, "count": value} for key, value in sorted(types.items(), key=lambda pair: (-pair[1], pair[0]))]}


def _completed_scans(repo, start: datetime, end: datetime, integration_id: str | None,
                     integration_ids: frozenset[str] = frozenset()):
    """Yield completed scans in a half-open interval, including older jobs."""
    for row in repo.dashboard_stages(start, integration_id):
        if integration_ids and row.get("integration_id") not in integration_ids:
            continue
        scan = row.get("scan_stage") or {}
        raw = scan.get("completed_at")
        if scan.get("state") != "completed" or not raw:
            continue
        at = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not start <= at < end:
            continue
        result = scan.get("result") or {}
        yield {"job_id": row.get("job_id"), "job_item_id": row.get("job_item_id"),
                     "object_identity": row.get("object_identity"), "completed_at": at.isoformat(),
                     "verdict": result.get("verdict") or "Unknown"}


def dashboard_scan_job_ids(repo, start: datetime, end: datetime, integration_id: str | None = None,
                           integration_ids: frozenset[str] = frozenset()) -> list[str]:
    return sorted({row["job_id"] for row in _completed_scans(repo, start, end, integration_id, integration_ids)
                   if row["job_id"]})


def dashboard_scans(repo, start: datetime, end: datetime, offset: int = 0, limit: int = 100,
                    integration_id: str | None = None) -> dict:
    rows = list(_completed_scans(repo, start, end, integration_id))
    rows.sort(key=lambda row: (row["completed_at"], row["job_item_id"] or ""), reverse=True)
    return {"total": len(rows), "offset": offset, "limit": limit, "scans": rows[offset:offset + limit]}
