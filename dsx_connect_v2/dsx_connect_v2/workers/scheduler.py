"""Submit due protected-scope scans through the manual scan submission path."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from dsx_connect_v2.api.routes.ui import UIScopeScanRequest, submit_scope_scan
from dsx_connect_v2.control_plane.scan_schedules import ScanScheduleStore
from dsx_connect_v2.jobs.postgres_repo import PostgresJobRepository
from dsx_connect_v2.jobs.service import JobService
from dsx_connect_v2.workers.runtime import build_job_service

log = logging.getLogger(__name__)
POLL_SECONDS = 20
MISSED_RUN_GRACE = timedelta(minutes=5)


async def run_due_schedule(store: ScanScheduleStore, service: JobService) -> bool:
    now = datetime.now(timezone.utc)
    with store.claim_due(now) as (conn, schedule):
        if schedule is None:
            return False
        due = schedule.next_run_at
        assert due is not None
        key = f"scheduled-scan:{schedule.scope_id}:{due.isoformat()}"
        outcome, reason, job_id = "submitted", None, None
        try:
            existing = service.repo.get_job_by_idempotency_key(key)
            if existing is not None:
                job_id = existing.job_id
                if not service.repo.summarize_job_items(job_id).total:
                    # Batch creation persists the parent before writing its
                    # items and outbox. A crash in that gap must not leave an
                    # empty job holding the scope guard indefinitely.
                    service.repo.update_job_state(
                        job_id, state="failed", error={"code": "scheduled_submission_interrupted"},
                        completed_at=now,
                    )
                    outcome, reason = "failed", "The previous submission was interrupted."
            elif now - due > MISSED_RUN_GRACE:
                outcome, reason = "skipped", "The scheduled start window was missed."
            else:
                result = await submit_scope_scan(
                    schedule.scope_id, UIScopeScanRequest(payload={"deferPublish": True}),
                    service.control_plane, service, idempotency_key=key,
                )
                job_id = result.job.job_id
        except HTTPException as exc:
            if exc.status_code == 409:
                outcome = "skipped"
            elif exc.status_code >= 500:
                raise  # Leave the occurrence due for retry within its start window.
            else:
                outcome = "failed"
            reason = str(exc.detail.get("message", exc.detail) if isinstance(exc.detail, dict) else exc.detail)
        store.finish(conn, schedule, outcome=outcome, reason=reason, job_id=job_id)
        return True


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    service, runtime = build_job_service()
    if not isinstance(service.repo, PostgresJobRepository) or service.control_plane is None or runtime["job_bus_backend"] != "rabbitmq":
        raise SystemExit("The scan scheduler requires PostgreSQL and RabbitMQ.")
    store = ScanScheduleStore(service.repo.db_url)
    while True:
        try:
            while await run_due_schedule(store, service):
                await asyncio.sleep(0)
        except Exception:
            log.exception("Scheduled scan submission failed. The worker will retry.")
        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
