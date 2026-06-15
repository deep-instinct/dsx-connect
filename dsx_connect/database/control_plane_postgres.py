from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.dsx_logging import dsx_logging


class ControlPlanePostgresRepo:
    """
    Optional PostgreSQL repository for preview write-through.

    This is intentionally synchronous and intended to be called through
    asyncio.to_thread(...) from async routes/startup.
    """

    def __init__(self, url: str, auto_apply_schema: bool = False):
        self.url = str(url).strip()
        self.auto_apply_schema = bool(auto_apply_schema)
        self._psycopg = None

    def initialize(self) -> None:
        try:
            import psycopg  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "psycopg is not installed; install psycopg to enable PostgreSQL preview mirroring"
            ) from e
        self._psycopg = psycopg
        self.healthcheck()
        if self.auto_apply_schema:
            self.apply_schema()

    def _connect(self):
        if self._psycopg is None:
            raise RuntimeError("ControlPlanePostgresRepo not initialized")
        return self._psycopg.connect(self.url, autocommit=False)

    def healthcheck(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.commit()

    def apply_schema(self) -> None:
        schema_file = Path(__file__).resolve().parent / "sql" / "control_plane_schema.sql"
        sql = schema_file.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        dsx_logging.info(f"Applied control-plane schema from {schema_file}")

    def _upsert_integration(self, cur, integration_external_id: str, platform: str = "preview") -> str:
        cur.execute(
            """
            INSERT INTO cp_integrations (name, platform, tenant_key, enabled, config_json)
            VALUES (%s, %s, %s, TRUE, '{}'::jsonb)
            ON CONFLICT (platform, tenant_key, name)
            DO UPDATE SET updated_at = now()
            RETURNING id::text
            """,
            (integration_external_id, platform, integration_external_id),
        )
        return cur.fetchone()[0]

    def _upsert_scope(
        self,
        cur,
        *,
        integration_id: str,
        external_scope_key: str,
        display_name: str,
        container: str,
        scope_type: str,
        resource_selector: str,
        filter_expression: str,
        mode: str,
        enabled: bool,
        post_scan_policy_json: dict[str, Any] | None = None,
    ) -> str:
        cur.execute(
            """
            INSERT INTO cp_scopes (
                integration_id, external_scope_key, display_name, container, scope_type,
                resource_selector, filter_expression, mode, enabled, post_scan_policy_json
            )
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (integration_id, external_scope_key)
            DO UPDATE SET
                display_name = EXCLUDED.display_name,
                container = EXCLUDED.container,
                scope_type = EXCLUDED.scope_type,
                resource_selector = EXCLUDED.resource_selector,
                filter_expression = EXCLUDED.filter_expression,
                mode = EXCLUDED.mode,
                enabled = EXCLUDED.enabled,
                post_scan_policy_json = EXCLUDED.post_scan_policy_json,
                updated_at = now()
            RETURNING id::text
            """,
            (
                integration_id,
                external_scope_key,
                display_name or "",
                container,
                scope_type,
                resource_selector,
                filter_expression or "",
                mode,
                bool(enabled),
                json.dumps(post_scan_policy_json or {}),
            ),
        )
        return cur.fetchone()[0]

    def upsert_scope_preview(self, scope_payload: dict[str, Any]) -> None:
        integration_external_id = str(scope_payload.get("integration_id") or "").strip()
        external_scope_key = str(scope_payload.get("scope_id") or "").strip()
        if not integration_external_id or not external_scope_key:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                integration_id = self._upsert_integration(cur, integration_external_id, platform=str(scope_payload.get("platform") or "preview"))
                self._upsert_scope(
                    cur,
                    integration_id=integration_id,
                    external_scope_key=external_scope_key,
                    display_name=str(scope_payload.get("display_name") or ""),
                    container=str(scope_payload.get("container") or "default"),
                    scope_type=str(scope_payload.get("scope_type") or "path"),
                    resource_selector=str(scope_payload.get("resource") or "/"),
                    filter_expression=str(scope_payload.get("filter") or ""),
                    mode=str(scope_payload.get("mode") or "monitor"),
                    enabled=bool(scope_payload.get("enabled", True)),
                    post_scan_policy_json={},
                )
            conn.commit()

    def delete_scope_preview(self, integration_external_id: str, external_scope_key: str) -> None:
        if not integration_external_id or not external_scope_key:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM cp_scopes s
                    USING cp_integrations i
                    WHERE s.integration_id = i.id
                      AND i.tenant_key = %s
                      AND s.external_scope_key = %s
                    """,
                    (integration_external_id, external_scope_key),
                )
            conn.commit()

    def upsert_full_scan_job_preview(
        self,
        *,
        integration_external_id: str,
        external_scope_key: str,
        external_full_scan_key: str,
        requested_by: str,
        status: str = "running",
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                integration_id = self._upsert_integration(cur, integration_external_id, platform="preview")
                scope_id = self._upsert_scope(
                    cur,
                    integration_id=integration_id,
                    external_scope_key=external_scope_key,
                    display_name=external_scope_key,
                    container="default",
                    scope_type="path",
                    resource_selector=f"/preview/{external_scope_key}",
                    filter_expression="",
                    mode="full_scan",
                    enabled=True,
                )
                cur.execute(
                    """
                    INSERT INTO cp_full_scan_jobs (
                        integration_id, scope_id, external_full_scan_key, status, requested_by, started_at
                    )
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s, now())
                    ON CONFLICT (external_full_scan_key)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        requested_by = EXCLUDED.requested_by,
                        updated_at = now()
                    """,
                    (integration_id, scope_id, external_full_scan_key, status, requested_by),
                )
            conn.commit()

    def upsert_job_preview(
        self,
        job_payload: dict[str, Any],
        *,
        full_scan_external_key: str | None = None,
    ) -> None:
        integration_external_id = str(job_payload.get("integration_id") or "").strip()
        if not integration_external_id:
            return
        external_scope_key = str(job_payload.get("scope_id") or "").strip()
        external_job_key = str(job_payload.get("job_id") or "").strip()
        if not external_job_key:
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                integration_id = self._upsert_integration(cur, integration_external_id, platform="preview")
                scope_id = None
                if external_scope_key:
                    scope_id = self._upsert_scope(
                        cur,
                        integration_id=integration_id,
                        external_scope_key=external_scope_key,
                        display_name=external_scope_key,
                        container="default",
                        scope_type="path",
                        resource_selector=f"/preview/{external_scope_key}",
                        filter_expression="",
                        mode="monitor",
                        enabled=True,
                    )

                full_scan_id = None
                ext_full = (full_scan_external_key or "").strip()
                if ext_full:
                    cur.execute("SELECT id::text FROM cp_full_scan_jobs WHERE external_full_scan_key = %s", (ext_full,))
                    row = cur.fetchone()
                    if row:
                        full_scan_id = row[0]

                idempotency_key = f"preview:{job_payload.get('job_type')}:{external_job_key}"
                cur.execute(
                    """
                    INSERT INTO cp_jobs (
                        external_job_key, job_type, state, integration_id, scope_id, full_scan_job_id,
                        object_identity, parent_job_id, root_job_id, correlation_id,
                        source_type, source_entity_id, idempotency_key, attempt, max_attempts,
                        outcome, outcome_reason, payload_json, created_at, updated_at, scheduled_at
                    )
                    VALUES (
                        %s, %s, %s, %s::uuid, %s::uuid, %s::uuid,
                        %s, NULL, NULL, NULL,
                        NULL, NULL, %s, %s, %s,
                        NULL, NULL, %s::jsonb, %s::timestamptz, %s::timestamptz, %s::timestamptz
                    )
                    ON CONFLICT (external_job_key)
                    DO UPDATE SET
                        state = EXCLUDED.state,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = now()
                    """,
                    (
                        external_job_key,
                        str(job_payload.get("job_type") or "UnknownJob"),
                        str(job_payload.get("state") or "queued"),
                        integration_id,
                        scope_id,
                        full_scan_id,
                        str(job_payload.get("payload", {}).get("object_identity") or ""),
                        idempotency_key,
                        int(job_payload.get("attempt") or 0),
                        int(job_payload.get("max_attempts") or 5),
                        json.dumps(job_payload.get("payload") or {}),
                        str(job_payload.get("created_at")),
                        str(job_payload.get("updated_at")),
                        str(job_payload.get("scheduled_at") or job_payload.get("created_at")),
                    ),
                )
            conn.commit()

    def list_scope_preview(self, limit: int = 200) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 5000))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        s.external_scope_key,
                        i.tenant_key,
                        i.platform,
                        s.container,
                        s.scope_type,
                        s.resource_selector,
                        s.filter_expression,
                        s.mode,
                        s.enabled,
                        s.display_name,
                        s.created_at,
                        s.updated_at
                    FROM cp_scopes s
                    JOIN cp_integrations i ON i.id = s.integration_id
                    ORDER BY s.created_at DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall()
            conn.commit()
        items: list[dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "scope_id": r[0],
                    "integration_id": r[1],
                    "platform": r[2],
                    "container": r[3],
                    "scope_type": r[4],
                    "resource": r[5],
                    "filter": r[6],
                    "mode": r[7],
                    "enabled": bool(r[8]),
                    "display_name": r[9] or "",
                    "created_at": r[10].isoformat() if r[10] else "",
                    "updated_at": r[11].isoformat() if r[11] else "",
                }
            )
        return items

    def list_job_preview(self, limit: int = 200) -> list[dict[str, Any]]:
        lim = max(1, min(int(limit), 5000))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        external_job_key,
                        job_type,
                        state,
                        i.tenant_key,
                        s.external_scope_key,
                        parent_job_id::text,
                        payload_json,
                        created_at,
                        updated_at
                    FROM cp_jobs j
                    JOIN cp_integrations i ON i.id = j.integration_id
                    LEFT JOIN cp_scopes s ON s.id = j.scope_id
                    ORDER BY j.created_at DESC
                    LIMIT %s
                    """,
                    (lim,),
                )
                rows = cur.fetchall()
            conn.commit()

        items: list[dict[str, Any]] = []
        for r in rows:
            items.append(
                {
                    "job_id": r[0],
                    "job_type": r[1],
                    "state": r[2],
                    "integration_id": r[3],
                    "scope_id": r[4],
                    "parent_job_id": r[5],
                    "payload": r[6] or {},
                    "created_at": r[7].isoformat() if r[7] else "",
                    "updated_at": r[8].isoformat() if r[8] else "",
                }
            )
        return items
