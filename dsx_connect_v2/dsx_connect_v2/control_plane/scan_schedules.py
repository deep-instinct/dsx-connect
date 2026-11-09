"""Durable daily and weekly schedules for protected scopes."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator


class ScanScheduleSettings(BaseModel):
    enabled: bool = True
    frequency: Literal["daily", "weekly"]
    local_time: time
    timezone: str = Field(min_length=1, max_length=128)
    weekday: int | None = Field(default=None, ge=0, le=6)

    @model_validator(mode="after")
    def validate_schedule(self) -> ScanScheduleSettings:
        if self.local_time.tzinfo is not None or self.local_time.second or self.local_time.microsecond:
            raise ValueError("Use a local time in HH:MM format")
        if (self.frequency == "weekly") != (self.weekday is not None):
            raise ValueError("A weekday is required only for weekly schedules")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use a valid IANA time zone") from exc
        return self


class ScanSchedule(ScanScheduleSettings):
    scope_id: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_outcome: Literal["submitted", "skipped", "failed"] | None
    last_reason: str | None
    last_job_id: str | None


def next_occurrence(schedule: ScanScheduleSettings, after: datetime) -> datetime:
    zone = ZoneInfo(schedule.timezone)
    local_date = after.astimezone(zone).date()
    for offset in range(8):
        day = local_date + timedelta(days=offset)
        if schedule.weekday is not None and day.weekday() != schedule.weekday:
            continue
        # First occurrence during a repeated hour. A nonexistent time moves
        # forward by the DST gap when converted back to local time.
        instant = datetime.combine(day, schedule.local_time, zone).astimezone(timezone.utc)
        if instant > after:
            return instant
    raise RuntimeError("Unable to calculate the next schedule occurrence")


class ScanScheduleStore:
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.db_url, row_factory=dict_row)

    def get(self, scope_id: str) -> ScanSchedule | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cp_scan_schedules WHERE scope_id = %s", (scope_id,)).fetchone()
        return ScanSchedule.model_validate(row) if row else None

    def save(self, scope_id: str, settings: ScanScheduleSettings) -> ScanSchedule:
        next_run = next_occurrence(settings, datetime.now(timezone.utc)) if settings.enabled else None
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO cp_scan_schedules (scope_id, enabled, frequency, local_time, timezone, weekday, next_run_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (scope_id) DO UPDATE SET
                    enabled = EXCLUDED.enabled, frequency = EXCLUDED.frequency,
                    local_time = EXCLUDED.local_time, timezone = EXCLUDED.timezone,
                    weekday = EXCLUDED.weekday,
                    next_run_at = CASE WHEN
                        (cp_scan_schedules.enabled, cp_scan_schedules.frequency, cp_scan_schedules.local_time,
                         cp_scan_schedules.timezone, cp_scan_schedules.weekday)
                        IS NOT DISTINCT FROM
                        (EXCLUDED.enabled, EXCLUDED.frequency, EXCLUDED.local_time, EXCLUDED.timezone, EXCLUDED.weekday)
                        THEN cp_scan_schedules.next_run_at ELSE EXCLUDED.next_run_at END
                RETURNING *
                """,
                (scope_id, settings.enabled, settings.frequency, settings.local_time,
                 settings.timezone, settings.weekday, next_run),
            ).fetchone()
        return ScanSchedule.model_validate(row)

    @contextmanager
    def claim_due(self, now: datetime):
        # Hold the row lock until submission and occurrence recording finish.
        # A process crash releases the lock and leaves the occurrence retryable.
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cp_scan_schedules
                WHERE enabled AND next_run_at <= %s
                ORDER BY next_run_at, scope_id
                LIMIT 1 FOR UPDATE SKIP LOCKED
                """,
                (now,),
            ).fetchone()
            yield conn, ScanSchedule.model_validate(row) if row else None

    def finish(self, conn, schedule: ScanSchedule, *, outcome: str, reason: str | None, job_id: str | None) -> None:
        conn.execute(
            """
            UPDATE cp_scan_schedules SET next_run_at = %s, last_run_at = %s,
                last_outcome = %s, last_reason = %s, last_job_id = %s
            WHERE scope_id = %s
            """,
            (next_occurrence(schedule, datetime.now(timezone.utc)), schedule.next_run_at,
             outcome, reason, job_id, schedule.scope_id),
        )
