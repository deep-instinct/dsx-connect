"""Historical file counts from persisted stages, independent of recent-job samples."""
from datetime import datetime, timedelta, timezone
from math import ceil
from statistics import median


def dashboard_history(repo, days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    hourly = days == 1
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    end_bucket = now.replace(minute=0, second=0, microsecond=0) if hourly else now.replace(hour=0, minute=0, second=0, microsecond=0)
    count = 24 if hourly else days
    start = end_bucket - step * (count - 1)
    buckets = [{"at": (start + step * i).isoformat(), "total": 0, "benign": 0, "malicious": 0, "suspicious": 0, "other": 0} for i in range(count)]
    quarantine = {"malicious": 0, "suspicious": 0, "file_type_policy": 0, "other": 0}
    blocked = 0
    types = {}

    backlog_changes = [0] * (count + 1)
    latency_samples = [[] for _ in buckets]
    latency_all = []

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

    for row in repo.dashboard_stages(start):
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
        at = in_window(scan)
        if scan.get("state") == "completed" and at:
            bucket = buckets[int((at - start) / step)]
            bucket["total"] += 1
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
    def latency_summary(samples):
        ordered = sorted(samples)
        return {"samples": len(ordered), "median_seconds": median(ordered) if ordered else None,
                "p95_seconds": ordered[ceil(len(ordered) * .95) - 1] if ordered else None}

    backlog = 0
    for i, bucket in enumerate(buckets):
        backlog += backlog_changes[i]
        elapsed_minutes = (min(start + step * (i + 1), now) - (start + step * i)).total_seconds() / 60
        bucket.update(throughput_per_minute=bucket["total"] / elapsed_minutes if elapsed_minutes > 0 else 0,
                      backlog=backlog, **latency_summary(latency_samples[i]))
    return {"days": days, "timezone": "UTC", "start": start.isoformat(), "end": now.isoformat(),
            "bucket": "hour" if hourly else "day", "series": buckets,
            "throughput_per_minute": sum(b["total"] for b in buckets) / max((now - start).total_seconds() / 60, 1 / 60),
            "backlog": backlog, "latency": latency_summary(latency_all),
            "total_scans": sum(b["total"] for b in buckets), "quarantined": quarantine,
            "file_type_policy_matches": blocked,
            "file_types": [{"type": key, "count": value} for key, value in sorted(types.items(), key=lambda pair: (-pair[1], pair[0]))]}
