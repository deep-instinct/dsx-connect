from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
import uuid

from dsx_connect_ng.jobs.models import (
    ContentSource,
    JobCreate,
    JobItemCreate,
    JobItemRecord,
    JobItemSummary,
    JobRecord,
    OutboxRecord,
    StageRecord,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobRepository(ABC):
    @abstractmethod
    def list_jobs(
        self,
        *,
        integration_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_job_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def create_job(self, payload: JobCreate) -> JobRecord:
        raise NotImplementedError

    @abstractmethod
    def update_job_state(
        self,
        job_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_job_items(self, *, job_id: str, state: str | None = None, limit: int = 1000) -> list[JobItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_job_item(self, job_item_id: str) -> JobItemRecord | None:
        raise NotImplementedError

    @abstractmethod
    def create_job_item(self, payload: JobItemCreate) -> JobItemRecord:
        raise NotImplementedError

    @abstractmethod
    def update_job_item_state(
        self,
        job_item_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobItemRecord | None:
        raise NotImplementedError

    @abstractmethod
    def update_job_item_stage(
        self,
        job_item_id: str,
        *,
        stage_name: str,
        stage_record: StageRecord,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobItemRecord | None:
        raise NotImplementedError

    @abstractmethod
    def summarize_job_items(self, job_id: str) -> JobItemSummary:
        raise NotImplementedError

    @abstractmethod
    def update_job_item_delivery_requirements(self, job_item_id: str, *, wait_for_dianna: bool) -> JobItemRecord | None:
        raise NotImplementedError

    @abstractmethod
    def update_job_item_content_source(self, job_item_id: str, content_source: ContentSource) -> JobItemRecord | None:
        raise NotImplementedError

    @abstractmethod
    def create_outbox_record(self, *, job: JobRecord, topic: str, payload: dict[str, Any]) -> OutboxRecord:
        raise NotImplementedError

    @abstractmethod
    def list_outbox_records(
        self,
        *,
        publish_state: str | None = None,
        limit: int = 100,
    ) -> list[OutboxRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_outbox_record(self, outbox_id: str) -> OutboxRecord | None:
        raise NotImplementedError

    @abstractmethod
    def claim_outbox_record(self, outbox_id: str) -> OutboxRecord | None:
        raise NotImplementedError

    @abstractmethod
    def mark_outbox_published(self, outbox_id: str) -> OutboxRecord | None:
        raise NotImplementedError

    @abstractmethod
    def mark_outbox_failed(self, outbox_id: str, *, error: dict[str, Any]) -> OutboxRecord | None:
        raise NotImplementedError


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._job_items: dict[str, JobItemRecord] = {}
        self._outbox: dict[str, OutboxRecord] = {}

    def list_jobs(
        self,
        *,
        integration_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        rows = list(self._jobs.values())
        if integration_id is not None:
            rows = [row for row in rows if row.integration_id == integration_id]
        if state is not None:
            rows = [row for row in rows if row.state == state]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[:limit]

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def get_job_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        for row in self._jobs.values():
            if row.idempotency_key == idempotency_key:
                return row
        return None

    def create_job(self, payload: JobCreate) -> JobRecord:
        job_id = payload.job_id or f"job_{uuid.uuid4().hex}"
        row = JobRecord(job_id=job_id, **payload.model_dump(exclude={"job_id"}))
        self._jobs[job_id] = row
        return row

    def update_job_state(
        self,
        job_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobRecord | None:
        current = self._jobs.get(job_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "state": state,
                "error": error,
                "updated_at": utcnow(),
                "completed_at": completed_at,
            }
        )
        self._jobs[job_id] = merged
        return merged

    def list_job_items(self, *, job_id: str, state: str | None = None, limit: int = 1000) -> list[JobItemRecord]:
        rows = [row for row in self._job_items.values() if row.job_id == job_id]
        if state is not None:
            rows = [row for row in rows if row.state == state]
        rows.sort(key=lambda row: row.item_index)
        return rows[:limit]

    def get_job_item(self, job_item_id: str) -> JobItemRecord | None:
        return self._job_items.get(job_item_id)

    def create_job_item(self, payload: JobItemCreate) -> JobItemRecord:
        job_item_id = payload.job_item_id or f"job_item_{uuid.uuid4().hex}"
        row = JobItemRecord(job_item_id=job_item_id, **payload.model_dump(exclude={"job_item_id"}))
        self._job_items[job_item_id] = row
        return row

    def update_job_item_state(
        self,
        job_item_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobItemRecord | None:
        current = self._job_items.get(job_item_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "state": state,
                "error": error,
                "updated_at": utcnow(),
                "completed_at": completed_at,
            }
        )
        self._job_items[job_item_id] = merged
        return merged

    def update_job_item_stage(
        self,
        job_item_id: str,
        *,
        stage_name: str,
        stage_record: StageRecord,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobItemRecord | None:
        current = self._job_items.get(job_item_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                stage_name: stage_record,
                "state": state,
                "error": error,
                "updated_at": utcnow(),
                "completed_at": completed_at,
            }
        )
        self._job_items[job_item_id] = merged
        return merged

    def summarize_job_items(self, job_id: str) -> JobItemSummary:
        summary = JobItemSummary()
        for row in self.list_job_items(job_id=job_id):
            summary.total += 1
            if row.state == "accepted":
                summary.accepted += 1
            elif row.state == "publish_pending":
                summary.publish_pending += 1
            elif row.state == "queued":
                summary.queued += 1
            elif row.state == "scanning":
                summary.scanning += 1
            elif row.state == "scanned":
                summary.scanned += 1
            elif row.state == "remediating":
                summary.remediating += 1
            elif row.state == "deliver_pending":
                summary.deliver_pending += 1
            elif row.state == "delivering_result":
                summary.delivering_result += 1
            elif row.state == "completed":
                summary.completed += 1
            elif row.state == "failed":
                summary.failed += 1
            elif row.state == "cancelled":
                summary.cancelled += 1
        return summary

    def update_job_item_delivery_requirements(self, job_item_id: str, *, wait_for_dianna: bool) -> JobItemRecord | None:
        current = self._job_items.get(job_item_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "delivery_requirements": current.delivery_requirements.model_copy(update={"wait_for_dianna": wait_for_dianna}),
                "updated_at": utcnow(),
            }
        )
        self._job_items[job_item_id] = merged
        return merged

    def update_job_item_content_source(self, job_item_id: str, content_source: ContentSource) -> JobItemRecord | None:
        current = self._job_items.get(job_item_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "content_source": content_source,
                "updated_at": utcnow(),
            }
        )
        self._job_items[job_item_id] = merged
        return merged

    def create_outbox_record(self, *, job: JobRecord, topic: str, payload: dict[str, Any]) -> OutboxRecord:
        outbox_id = f"outbox_{uuid.uuid4().hex}"
        row = OutboxRecord(
            outbox_id=outbox_id,
            job_id=job.job_id,
            topic=topic,
            payload=payload,
            publish_state="pending",
        )
        self._outbox[outbox_id] = row
        return row

    def list_outbox_records(
        self,
        *,
        publish_state: str | None = None,
        limit: int = 100,
    ) -> list[OutboxRecord]:
        rows = list(self._outbox.values())
        if publish_state is not None:
            rows = [row for row in rows if row.publish_state == publish_state]
        rows.sort(key=lambda row: row.created_at)
        return rows[:limit]

    def get_outbox_record(self, outbox_id: str) -> OutboxRecord | None:
        return self._outbox.get(outbox_id)

    def claim_outbox_record(self, outbox_id: str) -> OutboxRecord | None:
        current = self._outbox.get(outbox_id)
        if current is None or current.publish_state != "pending":
            return None
        merged = current.model_copy(
            update={
                "publish_state": "publishing",
                "updated_at": utcnow(),
            }
        )
        self._outbox[outbox_id] = merged
        return merged

    def mark_outbox_published(self, outbox_id: str) -> OutboxRecord | None:
        current = self._outbox.get(outbox_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "publish_state": "published",
                "publish_attempts": current.publish_attempts + 1,
                "updated_at": utcnow(),
                "published_at": utcnow(),
                "last_error": None,
            }
        )
        self._outbox[outbox_id] = merged
        return merged

    def mark_outbox_failed(self, outbox_id: str, *, error: dict[str, Any]) -> OutboxRecord | None:
        current = self._outbox.get(outbox_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                "publish_state": "pending",
                "publish_attempts": current.publish_attempts + 1,
                "updated_at": utcnow(),
                "last_error": error,
            }
        )
        self._outbox[outbox_id] = merged
        return merged
