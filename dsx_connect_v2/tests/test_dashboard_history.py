from datetime import datetime, timedelta, timezone

from dsx_connect_v2.jobs.dashboard import dashboard_history


NOW = datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc)


class HistoryRepo:
    def __init__(self, rows):
        self.rows = rows

    def dashboard_stages(self, since, integration_id=None):
        return iter(self.rows)

    def dashboard_jobs(self, since, end, integration_id=None):
        return iter(())


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


def test_scan_drilldown_matches_history_bucket_and_paginates():
    from dsx_connect_v2.jobs.dashboard import dashboard_scans

    start = NOW.replace(hour=0, minute=0)
    rows = [dict(row(verdict), job_id=f"job-{i}", job_item_id=f"item-{i}", object_identity=f"file-{i}")
            for i, verdict in enumerate(["Benign", "Malicious", "Suspicious"])]
    rows += [row(age=1), {"scan_stage": {"state": "pending"}}]
    repo = HistoryRepo(rows)
    first = dashboard_scans(repo, start, start + timedelta(days=1), limit=2)
    second = dashboard_scans(repo, start, start + timedelta(days=1), offset=2, limit=2)
    assert first["total"] == dashboard_history(repo, 7, NOW)["series"][-1]["total"] == 3
    assert len(first["scans"]) == 2
    assert len(second["scans"]) == 1
    assert {r["job_item_id"] for r in first["scans"] + second["scans"]} == {"item-0", "item-1", "item-2"}
    assert dashboard_scans(repo, NOW - timedelta(hours=1), NOW)["total"] == 0


def test_operator_metrics_keep_job_worker_and_engine_timing_separate_by_connector():
    from dsx_connect_v2.jobs.dashboard import dashboard_scans
    from dsx_connect_v2.jobs.models import JobItemRecord, JobRecord, StageRecord
    from dsx_connect_v2.jobs.repository import InMemoryJobRepository

    repo = InMemoryJobRepository()
    start = NOW.replace(minute=0) - timedelta(hours=23)
    current_start = start + timedelta(minutes=5)
    prior_start = start - timedelta(minutes=5)

    def add_scan(connector, key, queued, begins, finishes, *, worker_ms=2500, dsxa_us=500_000):
        job_created = queued - timedelta(seconds=5)
        persisted = finishes + timedelta(seconds=12)
        repo._jobs[key] = JobRecord(
            job_id=key, job_type="scan.batch", integration_id=connector, state="completed",
            created_at=job_created, completed_at=persisted,
        )
        repo._job_items[key] = JobItemRecord(
            job_item_id=key, job_id=key, item_index=0, object_identity=f"{key}.pdf",
            state="completed", created_at=queued, updated_at=persisted, completed_at=persisted,
            scan_stage=StageRecord(
                state="completed", completed_at=persisted,
                metadata={"workerStartedAt": begins.isoformat(), "workerFinishedAt": finishes.isoformat(),
                          "workerElapsedMs": worker_ms, "requestElapsedMs": 100},
                result={"verdict": "Benign", "scan_duration_in_microseconds": dsxa_us},
            ),
        )

    add_scan("a", "a-first", current_start, current_start + timedelta(seconds=1),
             current_start + timedelta(seconds=2))
    add_scan("a", "a-second", current_start, current_start + timedelta(seconds=4),
             current_start + timedelta(seconds=5), worker_ms=3500, dsxa_us=None)
    add_scan("a", "a-prior-first", prior_start, prior_start + timedelta(seconds=1),
             prior_start + timedelta(seconds=2))
    add_scan("a", "a-prior-second", prior_start, prior_start + timedelta(seconds=8),
             prior_start + timedelta(seconds=9))
    add_scan("b", "b-first", current_start, current_start + timedelta(seconds=10),
             current_start + timedelta(seconds=11))

    data = dashboard_history(repo, 1, NOW, integration_id="a")
    assert data["total_scans"] == 2
    assert data["jobs"] == {"completed": 2, "failed": 0, "cancelled": 0}
    assert data["job_duration"] == {"samples": 2, "median_seconds": 20.5, "p95_seconds": 22}
    assert data["scan_worker"] == {"samples": 2, "median_seconds": 3, "p95_seconds": 3.5}
    assert data["dsxa"] == {"samples": 1, "median_seconds": 0.5, "p95_seconds": 0.5}
    assert data["under_load"] == {
        "current": {"scans": 0, "waiting_seconds": 0, "files_per_second": None},
        "previous": {"scans": 0, "waiting_seconds": 0, "files_per_second": None},
    }
    assert dashboard_history(repo, 1, NOW, integration_id="b")["total_scans"] == 1
    assert dashboard_scans(repo, start, start + timedelta(hours=1), integration_id="a")["total"] == 2


def test_under_load_trend_ranks_five_connectors_and_keeps_empty_buckets():
    class ConnectorHistoryRepo(HistoryRepo):
        def dashboard_stages(self, since, integration_id=None):
            return (item for item in self.rows if integration_id is None or item["integration_id"] == integration_id)

    rows = []
    for connector in range(1, 7):
        connector_id = f"connector-{connector}"
        queued = NOW - timedelta(minutes=5)
        for i in range(connector):
            begins = queued + timedelta(seconds=20 * i + 10)
            finishes = begins + timedelta(seconds=1)
            item = timed_item(queued, finishes, "completed")
            item["integration_id"] = connector_id
            item["scan_stage"] = {"state": "completed", "started_at": begins.isoformat(),
                                  "completed_at": finishes.isoformat()}
            rows.append(item)

    repo = ConnectorHistoryRepo(rows)
    data = dashboard_history(repo, 1, NOW)
    assert [line["integration_id"] for line in data["under_load_series"]] == [
        "connector-6", "connector-5", "connector-4", "connector-3", "connector-2",
    ]
    assert data["under_load_series"][0]["files_per_second"] == [None] * 23 + [5 / 110]
    assert data["under_load_series"][0]["completed_scans"] == [0] * 23 + [6]
    filtered = dashboard_history(repo, 1, NOW, integration_id="connector-1")
    assert filtered["under_load_series"] == [
        {"integration_id": "connector-1", "files_per_second": [None] * 24,
         "completed_scans": [0] * 23 + [1]},
    ]


def test_history_cache_reuses_snapshot_until_expiry_and_keeps_filters_distinct(monkeypatch):
    from dsx_connect_v2.jobs import dashboard

    clock = [0]
    calls = []
    monkeypatch.setattr(dashboard, "monotonic", lambda: clock[0])
    monkeypatch.setattr(dashboard, "dashboard_history",
                        lambda repo, days, integration_id: calls.append((repo, days, integration_id)) or {})
    repo = HistoryRepo([])
    cache = dashboard.DashboardHistoryCache()
    assert cache.get(repo, 7, None) is cache.get(repo, 7, None)
    cache.get(repo, 1, None)
    cache.get(repo, 7, "connector")
    assert len(calls) == 3
    clock[0] += 16
    cache.get(repo, 7, None)
    assert len(calls) == 4



def test_under_load_zero_requires_continuous_waiting():
    from collections import Counter

    from dsx_connect_v2.jobs.dashboard import _throughput_under_load

    start = NOW - timedelta(minutes=4)
    t = lambda seconds: start + timedelta(seconds=seconds)
    changes = Counter({t(-50): 1, t(-10): -1, t(0): 1, t(20): -1,
                       t(30): 1, t(50): -1, t(70): 1, t(100): -1})
    completions = Counter({t(-20): 2, t(10): 1, t(40): 1, t(110): 1})
    result, series = _throughput_under_load(changes, completions, [t(0), t(60)], NOW)
    assert series == [None, 0]
    assert result == {
        "current": {"scans": 0, "waiting_seconds": 30, "files_per_second": 0},
        "previous": {"scans": 2, "waiting_seconds": 40, "files_per_second": 0.05},
    }
