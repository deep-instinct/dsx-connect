from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import psycopg
from psycopg.rows import dict_row

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
from dsx_connect_ng.jobs.repository import JobRepository


def _migration_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


def migration_files() -> list[Path]:
    return sorted(_migration_dir().glob("*.sql"))


def apply_schema(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for migration in migration_files():
                cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()


class PostgresJobRepository(JobRepository):
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def _connect(self):
        return psycopg.connect(self.db_url, row_factory=dict_row)

    def list_jobs(
        self,
        *,
        integration_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        query = """
            SELECT job_id, job_type, state, integration_id, scope_id, object_identity,
                   idempotency_key, payload_json AS payload, error_json AS error,
                   created_at, updated_at, completed_at
            FROM cp_jobs
            WHERE 1 = 1
        """
        params: list[Any] = []
        if integration_id is not None:
            query += " AND integration_id = %s"
            params.append(integration_id)
        if state is not None:
            query += " AND state = %s"
            params.append(state)
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return [JobRecord.model_validate(row) for row in cur.fetchall()]

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, job_type, state, integration_id, scope_id, object_identity,
                       idempotency_key, payload_json AS payload, error_json AS error,
                       created_at, updated_at, completed_at
                FROM cp_jobs
                WHERE job_id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return JobRecord.model_validate(row) if row else None

    def get_job_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, job_type, state, integration_id, scope_id, object_identity,
                       idempotency_key, payload_json AS payload, error_json AS error,
                       created_at, updated_at, completed_at
                FROM cp_jobs
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = cur.fetchone()
            return JobRecord.model_validate(row) if row else None

    def create_job(self, payload: JobCreate) -> JobRecord:
        job_id = payload.job_id or f"job_{uuid.uuid4().hex}"
        data = payload.model_dump(exclude={"job_id"})
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_jobs (
                    job_id, job_type, state, integration_id, scope_id, object_identity,
                    idempotency_key, payload_json, error_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING job_id, job_type, state, integration_id, scope_id, object_identity,
                          idempotency_key, payload_json AS payload, error_json AS error,
                          created_at, updated_at, completed_at
                """,
                (
                    job_id,
                    data["job_type"],
                    data["state"],
                    data["integration_id"],
                    data["scope_id"],
                    data["object_identity"],
                    data["idempotency_key"],
                    psycopg.types.json.Json(data["payload"]),
                    psycopg.types.json.Json(data["error"]),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return JobRecord.model_validate(row)

    def update_job_state(
        self,
        job_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_jobs
                SET state = %s,
                    error_json = %s::jsonb,
                    completed_at = %s,
                    updated_at = NOW()
                WHERE job_id = %s
                RETURNING job_id, job_type, state, integration_id, scope_id, object_identity,
                          idempotency_key, payload_json AS payload, error_json AS error,
                          created_at, updated_at, completed_at
                """,
                (state, psycopg.types.json.Json(error), completed_at, job_id),
            )
            row = cur.fetchone()
            conn.commit()
            return JobRecord.model_validate(row) if row else None

    def list_job_items(self, *, job_id: str, state: str | None = None, limit: int = 1000) -> list[JobItemRecord]:
        query = """
            SELECT job_item_id, job_id, item_index, object_identity, state,
                   payload_json AS payload, content_source_json AS content_source,
                   delivery_requirements_json AS delivery_requirements, error_json AS error,
                   scan_stage_json AS scan_stage,
                   policy_stage_json AS policy_stage,
                   remediation_stage_json AS remediation_stage,
                   delivery_stage_json AS delivery_stage,
                   dianna_stage_json AS dianna_stage,
                   created_at, updated_at, completed_at
            FROM cp_job_items
            WHERE job_id = %s
        """
        params: list[Any] = [job_id]
        if state is not None:
            query += " AND state = %s"
            params.append(state)
        query += " ORDER BY item_index LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return [JobItemRecord.model_validate(row) for row in cur.fetchall()]

    def get_job_item(self, job_item_id: str) -> JobItemRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_item_id, job_id, item_index, object_identity, state,
                       payload_json AS payload, content_source_json AS content_source,
                       delivery_requirements_json AS delivery_requirements, error_json AS error,
                       scan_stage_json AS scan_stage,
                       policy_stage_json AS policy_stage,
                       remediation_stage_json AS remediation_stage,
                       delivery_stage_json AS delivery_stage,
                       dianna_stage_json AS dianna_stage,
                       created_at, updated_at, completed_at
                FROM cp_job_items
                WHERE job_item_id = %s
                """,
                (job_item_id,),
            )
            row = cur.fetchone()
            return JobItemRecord.model_validate(row) if row else None

    def create_job_item(self, payload: JobItemCreate) -> JobItemRecord:
        job_item_id = payload.job_item_id or f"job_item_{uuid.uuid4().hex}"
        data = payload.model_dump(exclude={"job_item_id"})
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_job_items (
                    job_item_id, job_id, item_index, object_identity, state, payload_json, error_json,
                    content_source_json, delivery_requirements_json, scan_stage_json, policy_stage_json, remediation_stage_json, delivery_stage_json, dianna_stage_json
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                RETURNING job_item_id, job_id, item_index, object_identity, state,
                          payload_json AS payload, content_source_json AS content_source,
                          delivery_requirements_json AS delivery_requirements, error_json AS error,
                          scan_stage_json AS scan_stage,
                          policy_stage_json AS policy_stage,
                          remediation_stage_json AS remediation_stage,
                          delivery_stage_json AS delivery_stage,
                          dianna_stage_json AS dianna_stage,
                          created_at, updated_at, completed_at
                """,
                (
                    job_item_id,
                    data["job_id"],
                    data["item_index"],
                    data["object_identity"],
                    data["state"],
                    psycopg.types.json.Json(data["payload"]),
                    psycopg.types.json.Json(data["error"]),
                    psycopg.types.json.Json(data["content_source"]),
                    psycopg.types.json.Json(data["delivery_requirements"]),
                    psycopg.types.json.Json(data["scan_stage"]),
                    psycopg.types.json.Json(data["policy_stage"]),
                    psycopg.types.json.Json(data["remediation_stage"]),
                    psycopg.types.json.Json(data["delivery_stage"]),
                    psycopg.types.json.Json(data["dianna_stage"]),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return JobItemRecord.model_validate(row)

    def update_job_item_state(
        self,
        job_item_id: str,
        *,
        state: str,
        error: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> JobItemRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_job_items
                SET state = %s,
                    error_json = %s::jsonb,
                    completed_at = %s,
                    updated_at = NOW()
                WHERE job_item_id = %s
                RETURNING job_item_id, job_id, item_index, object_identity, state,
                          payload_json AS payload, content_source_json AS content_source,
                          delivery_requirements_json AS delivery_requirements, error_json AS error,
                          scan_stage_json AS scan_stage,
                          policy_stage_json AS policy_stage,
                          remediation_stage_json AS remediation_stage,
                          delivery_stage_json AS delivery_stage,
                          dianna_stage_json AS dianna_stage,
                          created_at, updated_at, completed_at
                """,
                (state, psycopg.types.json.Json(error), completed_at, job_item_id),
            )
            row = cur.fetchone()
            conn.commit()
            return JobItemRecord.model_validate(row) if row else None

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
        stage_column = {
            "scan_stage": "scan_stage_json",
            "policy_stage": "policy_stage_json",
            "remediation_stage": "remediation_stage_json",
            "delivery_stage": "delivery_stage_json",
            "dianna_stage": "dianna_stage_json",
        }.get(stage_name)
        if stage_column is None:
            raise ValueError(f"unsupported_stage:{stage_name}")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE cp_job_items
                SET {stage_column} = %s::jsonb,
                    state = %s,
                    error_json = %s::jsonb,
                    completed_at = %s,
                    updated_at = NOW()
                WHERE job_item_id = %s
                RETURNING job_item_id, job_id, item_index, object_identity, state,
                          payload_json AS payload, content_source_json AS content_source,
                          delivery_requirements_json AS delivery_requirements, error_json AS error,
                          scan_stage_json AS scan_stage,
                          policy_stage_json AS policy_stage,
                          remediation_stage_json AS remediation_stage,
                          delivery_stage_json AS delivery_stage,
                          dianna_stage_json AS dianna_stage,
                          created_at, updated_at, completed_at
                """,
                (
                    psycopg.types.json.Json(stage_record.model_dump(mode="json")),
                    state,
                    psycopg.types.json.Json(error),
                    completed_at,
                    job_item_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return JobItemRecord.model_validate(row) if row else None

    def update_job_item_delivery_requirements(self, job_item_id: str, *, wait_for_dianna: bool) -> JobItemRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_job_items
                SET delivery_requirements_json = %s::jsonb,
                    updated_at = NOW()
                WHERE job_item_id = %s
                RETURNING job_item_id, job_id, item_index, object_identity, state,
                          payload_json AS payload, content_source_json AS content_source,
                          delivery_requirements_json AS delivery_requirements, error_json AS error,
                          scan_stage_json AS scan_stage,
                          policy_stage_json AS policy_stage,
                          remediation_stage_json AS remediation_stage,
                          delivery_stage_json AS delivery_stage,
                          dianna_stage_json AS dianna_stage,
                          created_at, updated_at, completed_at
                """,
                (
                    psycopg.types.json.Json({"wait_for_dianna": wait_for_dianna}),
                    job_item_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return JobItemRecord.model_validate(row) if row else None

    def update_job_item_content_source(self, job_item_id: str, content_source: ContentSource) -> JobItemRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_job_items
                SET content_source_json = %s::jsonb,
                    updated_at = NOW()
                WHERE job_item_id = %s
                RETURNING job_item_id, job_id, item_index, object_identity, state,
                          payload_json AS payload, content_source_json AS content_source,
                          delivery_requirements_json AS delivery_requirements, error_json AS error,
                          scan_stage_json AS scan_stage,
                          policy_stage_json AS policy_stage,
                          remediation_stage_json AS remediation_stage,
                          delivery_stage_json AS delivery_stage,
                          dianna_stage_json AS dianna_stage,
                          created_at, updated_at, completed_at
                """,
                (
                    psycopg.types.json.Json(content_source.model_dump(mode="json")),
                    job_item_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return JobItemRecord.model_validate(row) if row else None

    def summarize_job_items(self, job_id: str) -> JobItemSummary:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM cp_job_items
                WHERE job_id = %s
                GROUP BY state
                """,
                (job_id,),
            )
            summary = JobItemSummary()
            for row in cur.fetchall():
                state = row["state"]
                count = int(row["count"])
                summary.total += count
                if state == "accepted":
                    summary.accepted = count
                elif state == "publish_pending":
                    summary.publish_pending = count
                elif state == "queued":
                    summary.queued = count
                elif state == "scanning":
                    summary.scanning = count
                elif state == "scanned":
                    summary.scanned = count
                elif state == "remediating":
                    summary.remediating = count
                elif state == "deliver_pending":
                    summary.deliver_pending = count
                elif state == "delivering_result":
                    summary.delivering_result = count
                elif state == "completed":
                    summary.completed = count
                elif state == "failed":
                    summary.failed = count
                elif state == "cancelled":
                    summary.cancelled = count
            return summary

    def create_outbox_record(self, *, job: JobRecord, topic: str, payload: dict[str, Any]) -> OutboxRecord:
        outbox_id = f"outbox_{uuid.uuid4().hex}"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_job_outbox (
                    outbox_id, job_id, topic, payload_json, publish_state, publish_attempts
                ) VALUES (%s, %s, %s, %s::jsonb, 'pending', 0)
                RETURNING outbox_id, job_id, topic, payload_json AS payload,
                          publish_state, publish_attempts, last_error_json AS last_error,
                          created_at, updated_at, published_at
                """,
                (outbox_id, job.job_id, topic, psycopg.types.json.Json(payload)),
            )
            row = cur.fetchone()
            conn.commit()
            return OutboxRecord.model_validate(row)

    def list_outbox_records(
        self,
        *,
        publish_state: str | None = None,
        limit: int = 100,
    ) -> list[OutboxRecord]:
        query = """
            SELECT outbox_id, job_id, topic, payload_json AS payload,
                   publish_state, publish_attempts, last_error_json AS last_error,
                   created_at, updated_at, published_at
            FROM cp_job_outbox
            WHERE 1 = 1
        """
        params: list[Any] = []
        if publish_state is not None:
            query += " AND publish_state = %s"
            params.append(publish_state)
        query += " ORDER BY created_at LIMIT %s"
        params.append(limit)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return [OutboxRecord.model_validate(row) for row in cur.fetchall()]

    def get_outbox_record(self, outbox_id: str) -> OutboxRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT outbox_id, job_id, topic, payload_json AS payload,
                       publish_state, publish_attempts, last_error_json AS last_error,
                       created_at, updated_at, published_at
                FROM cp_job_outbox
                WHERE outbox_id = %s
                """,
                (outbox_id,),
            )
            row = cur.fetchone()
            return OutboxRecord.model_validate(row) if row else None

    def mark_outbox_published(self, outbox_id: str) -> OutboxRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_job_outbox
                SET publish_state = 'published',
                    publish_attempts = publish_attempts + 1,
                    last_error_json = NULL,
                    published_at = NOW(),
                    updated_at = NOW()
                WHERE outbox_id = %s
                RETURNING outbox_id, job_id, topic, payload_json AS payload,
                          publish_state, publish_attempts, last_error_json AS last_error,
                          created_at, updated_at, published_at
                """,
                (outbox_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return OutboxRecord.model_validate(row) if row else None

    def mark_outbox_failed(self, outbox_id: str, *, error: dict[str, Any]) -> OutboxRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_job_outbox
                SET publish_state = 'pending',
                    publish_attempts = publish_attempts + 1,
                    last_error_json = %s::jsonb,
                    updated_at = NOW()
                WHERE outbox_id = %s
                RETURNING outbox_id, job_id, topic, payload_json AS payload,
                          publish_state, publish_attempts, last_error_json AS last_error,
                          created_at, updated_at, published_at
                """,
                (psycopg.types.json.Json(error), outbox_id),
            )
            row = cur.fetchone()
            conn.commit()
            return OutboxRecord.model_validate(row) if row else None
