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
