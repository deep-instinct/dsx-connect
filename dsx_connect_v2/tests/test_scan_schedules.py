import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from dsx_connect_v2.api.routes import ui
from dsx_connect_v2.control_plane.models import IntegrationCreate, ProtectedScopeCreate
from dsx_connect_v2.control_plane.postgres_repo import PostgresControlPlaneRepository, apply_schema
from dsx_connect_v2.control_plane.scan_schedules import ScanScheduleSettings, ScanScheduleStore, next_occurrence
from dsx_connect_v2.control_plane.service import ControlPlaneService
from dsx_connect_v2.jobs.bus import InMemoryJobBus
from dsx_connect_v2.jobs.postgres_repo import PostgresJobRepository
from dsx_connect_v2.jobs.service import JobService
from dsx_connect_v2.workers.scheduler import run_due_schedule


def test_weekly_schedule_preserves_wall_time_across_dst() -> None:
    schedule = ScanScheduleSettings(frequency="weekly", weekday=0, local_time="02:00", timezone="America/Chicago")
    assert next_occurrence(schedule, datetime(2026, 3, 2, 8, tzinfo=timezone.utc)) == datetime(
        2026, 3, 9, 7, tzinfo=timezone.utc,
    )


def test_daily_schedule_runs_only_once_in_repeated_hour() -> None:
    schedule = ScanScheduleSettings(frequency="daily", local_time="01:30", timezone="America/Chicago")
    first = next_occurrence(schedule, datetime(2026, 11, 1, 5, tzinfo=timezone.utc))
    assert first == datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc)
    assert next_occurrence(schedule, first) == datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)


def test_daily_schedule_shifts_forward_during_spring_gap() -> None:
    schedule = ScanScheduleSettings(frequency="daily", local_time="02:30", timezone="America/Chicago")
    assert next_occurrence(schedule, datetime(2026, 3, 8, 6, tzinfo=timezone.utc)) == datetime(
        2026, 3, 8, 8, 30, tzinfo=timezone.utc,
    )


def test_postgres_schedule_claim_submission_recovery_and_overlap(monkeypatch) -> None:
    db_url = os.environ.get("DSX_CONNECT_V2_TEST_POSTGRES_URL")
    if not db_url:
        pytest.skip("set DSX_CONNECT_V2_TEST_POSTGRES_URL to run the scheduler integration test")
    apply_schema(db_url)
    repo = PostgresControlPlaneRepository(db_url)
    control = ControlPlaneService(repo=repo)
    integration = control.create_integration(IntegrationCreate(
        platform="gcs", platform_key=f"schedule-{uuid.uuid4().hex}", display_name="Schedule test",
    ))
    scope = control.create_scope(ProtectedScopeCreate(
        integration_id=integration.integration_id, scope_type="path", resource_selector="test-bucket",
        display_name="Schedule test", mode="full_scan",
    ))
    service = JobService(repo=PostgresJobRepository(db_url), bus=InMemoryJobBus(), control_plane=control)
    store = ScanScheduleStore(db_url)
    monkeypatch.setattr(ui, "_connector_asset_endpoint", lambda *_: ("http://connector", "gcs"))
    monkeypatch.setattr(ui, "_fetch_connector_object_listing", lambda *_, **__: (
        [{"identity": "test-bucket/sample.txt", "location": "sample.txt"}], True, 1,
    ))
    monkeypatch.setattr(ui.settings, "scan_scheduler_enabled", True)
    settings = ScanScheduleSettings(frequency="daily", local_time="02:00", timezone="UTC")

    def set_due(due: datetime) -> None:
        import psycopg

        with psycopg.connect(db_url) as conn:
            conn.execute("UPDATE cp_scan_schedules SET next_run_at = %s WHERE scope_id = %s", (due, scope.scope_id))

    try:
        assert ui.get_scan_schedule(scope.scope_id, control, service) is None
        assert ui.save_scan_schedule(scope.scope_id, settings, control, service).enabled
        due = datetime.now(timezone.utc) - timedelta(seconds=1)
        set_due(due)
        with store.claim_due(datetime.now(timezone.utc)) as (_, claimed):
            assert claimed is not None and claimed.scope_id == scope.scope_id
            with store.claim_due(datetime.now(timezone.utc)) as (_, competing):
                assert competing is None

        assert asyncio.run(run_due_schedule(store, service))
        saved = store.get(scope.scope_id)
        assert saved is not None and saved.last_outcome == "submitted" and saved.last_job_id
        job = service.get_batch_job_or_404(saved.last_job_id)
        assert job.job.payload["source"] == "scheduled_scope_scan"
        assert job.item_summary.total == 1

        # Simulate a committed submission followed by a rolled-back occurrence update.
        set_due(due)
        assert asyncio.run(run_due_schedule(store, service))
        recovered = store.get(scope.scope_id)
        assert recovered is not None and recovered.last_job_id == saved.last_job_id

        set_due(due - timedelta(seconds=1))
        assert asyncio.run(run_due_schedule(store, service))
        skipped = store.get(scope.scope_id)
        assert skipped is not None and skipped.last_outcome == "skipped"
        assert "already active" in (skipped.last_reason or "")

        set_due(due - timedelta(hours=1))
        assert asyncio.run(run_due_schedule(store, service))
        missed = store.get(scope.scope_id)
        assert missed is not None and missed.last_reason == "The scheduled start window was missed."

        paused = ui.save_scan_schedule(scope.scope_id, settings.model_copy(update={"enabled": False}), control, service)
        assert not paused.enabled and paused.next_run_at is None
    finally:
        import psycopg

        with psycopg.connect(db_url) as conn:
            conn.execute("DELETE FROM cp_jobs WHERE scope_id = %s", (scope.scope_id,))
            conn.execute("DELETE FROM cp_integrations WHERE integration_id = %s", (integration.integration_id,))
