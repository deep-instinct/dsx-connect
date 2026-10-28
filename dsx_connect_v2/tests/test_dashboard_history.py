from datetime import datetime, timedelta, timezone

from dsx_connect_v2.jobs.dashboard import dashboard_history


NOW = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)


class HistoryRepo:
    def __init__(self, rows):
        self.rows = rows

    def dashboard_stages(self, since):
        return iter(self.rows)


def row(verdict="Benign", *, age=0, quarantine=False, reason=None, outcome="succeeded"):
    at = (NOW - timedelta(days=age)).isoformat()
    return {
        "scan_stage": {"state": "completed", "completed_at": at, "result": {"verdict": verdict, "file_info": {"file_type": "PDF"}}},
        "policy_stage": {"state": "completed", "completed_at": at, "result": {"policy_stage_result": {"decision_trace": {"policy_reason": reason}}}},
        "remediation_stage": {"state": "completed" if quarantine else "pending", "completed_at": at if quarantine else None, "result": {"action": "quarantine", "outcome": outcome}},
    }


def test_history_counts_files_not_jobs_and_limits_time_window():
    rows = [row(), row("Malicious"), row("Suspicious", age=6), row(age=8)]
    result = dashboard_history(HistoryRepo(rows), 7, NOW)
    assert result["total_scans"] == 3
    assert len(result["series"]) == 7
    assert sum(b["benign"] for b in result["series"]) == 1
    assert sum(b["malicious"] for b in result["series"]) == 1
    assert result["file_types"] == [{"type": "PDF", "count": 3}]
    assert len(dashboard_history(HistoryRepo(rows), 1, NOW)["series"]) == 24
    assert dashboard_history(HistoryRepo(rows), 30, NOW)["total_scans"] == 4


def test_quarantine_cause_and_success_are_separate_from_policy_match():
    rows = [row("Malicious", quarantine=True), row(quarantine=True, reason="blocked_file_type:pdf"),
            row("Malicious", quarantine=True, reason="blocked_file_type:exe"),
            row(quarantine=True, reason="blocked_file_type:zip", outcome="failed"), row("Suspicious", quarantine=True)]
    result = dashboard_history(HistoryRepo(rows), 7, NOW)
    assert result["quarantined"] == {"malicious": 1, "file_type_policy": 2, "suspicious": 1, "other": 0}
    assert result["file_type_policy_matches"] == 3


def test_pending_failed_and_future_scans_do_not_count():
    pending = row()
    pending["scan_stage"]["state"] = "running"
    failed = row()
    failed["scan_stage"]["state"] = "failed"
    future = row(age=-1)
    assert dashboard_history(HistoryRepo([pending, failed, future]), 7, NOW)["total_scans"] == 0


def timed_item(created, completed=None, state="queued"):
    return {"created_at": created.isoformat(), "completed_at": completed.isoformat() if completed else None,
            "state": state, "scan_stage": {}, "policy_stage": {}, "remediation_stage": {}}


def test_backlog_includes_old_unfinished_items_and_excludes_finished_and_future_items():
    rows = [timed_item(NOW - timedelta(days=40)),
            timed_item(NOW - timedelta(hours=2), NOW - timedelta(hours=1), "cancelled"),
            timed_item(NOW - timedelta(hours=1), NOW - timedelta(minutes=10), "failed"),
            timed_item(NOW + timedelta(hours=1)),
            timed_item(NOW - timedelta(days=40), NOW - timedelta(days=30), "completed")]
    result = dashboard_history(HistoryRepo(rows), 1, NOW)
    assert result["backlog"] == 1
    assert result["series"][-3]["backlog"] == 2
    assert result["series"][-2]["backlog"] == 2
    assert result["series"][-1]["backlog"] == 1
    assert result["latency"]["samples"] == 0
    assert result["latency"]["p95_seconds"] is None


def test_throughput_uses_elapsed_current_bucket_and_latency_uses_successful_completion():
    rows = []
    for seconds in [10, 20, 30, 40, 100]:
        item = row()
        item.update(timed_item(NOW - timedelta(seconds=seconds), NOW, "completed"))
        item["scan_stage"] = row()["scan_stage"]
        rows.append(item)
    rows.append(timed_item(NOW - timedelta(seconds=900), NOW, "failed"))
    result = dashboard_history(HistoryRepo(rows), 1, NOW)
    assert result["series"][-1]["throughput_per_minute"] == 5 / 30
    assert result["latency"] == {"samples": 5, "median_seconds": 30, "p95_seconds": 100}
    assert result["series"][-1]["median_seconds"] == 30
    assert result["series"][-2]["median_seconds"] is None
    assert result["backlog"] == 0


def test_bucket_boundaries_and_zero_elapsed_time():
    boundary = NOW.replace(minute=0)
    rows = [timed_item(boundary, boundary, "completed"), timed_item(boundary)]
    result = dashboard_history(HistoryRepo(rows), 1, boundary)
    assert result["backlog"] == 1
    assert result["series"][-1]["throughput_per_minute"] == 0
    assert result["latency"]["median_seconds"] == 0


def test_repository_history_keeps_stale_unfinished_work():
    from dsx_connect_v2.jobs.models import JobItemRecord
    from dsx_connect_v2.jobs.repository import InMemoryJobRepository

    repo = InMemoryJobRepository()
    old = NOW - timedelta(days=40)
    repo._job_items["old-queued"] = JobItemRecord(
        job_item_id="old-queued", job_id="job-old", item_index=0,
        object_identity="old.pdf", state="queued", created_at=old, updated_at=old)
    result = dashboard_history(repo, 1, NOW)
    assert result["backlog"] == 1
    assert all(bucket["backlog"] == 1 for bucket in result["series"])
