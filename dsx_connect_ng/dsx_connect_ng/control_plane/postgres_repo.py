from __future__ import annotations

import uuid

import psycopg
from psycopg.rows import dict_row

from dsx_connect_ng.control_plane.models import (
    IntegrationCreate,
    IntegrationRecord,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeRecord,
    ProtectedScopeUpdate,
)
from dsx_connect_ng.control_plane.repository import ControlPlaneRepository
from dsx_connect_ng.jobs.postgres_repo import migration_files


def apply_schema(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for migration in migration_files():
                cur.execute(migration.read_text(encoding="utf-8"))
        conn.commit()


class PostgresControlPlaneRepository(ControlPlaneRepository):
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def _connect(self):
        return psycopg.connect(self.db_url, row_factory=dict_row)

    def list_integrations(self) -> list[IntegrationRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT integration_id, platform, platform_key, display_name, enabled,
                       capability_discover, capability_monitor, capability_enumerate,
                       capability_read, capability_remediate, config_json AS config,
                       created_at, updated_at
                FROM cp_integrations
                ORDER BY created_at
                """
            )
            return [IntegrationRecord.model_validate(row) for row in cur.fetchall()]

    def get_integration(self, integration_id: str) -> IntegrationRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT integration_id, platform, platform_key, display_name, enabled,
                       capability_discover, capability_monitor, capability_enumerate,
                       capability_read, capability_remediate, config_json AS config,
                       created_at, updated_at
                FROM cp_integrations
                WHERE integration_id = %s
                """,
                (integration_id,),
            )
            row = cur.fetchone()
            return IntegrationRecord.model_validate(row) if row else None

    def create_integration(self, payload: IntegrationCreate) -> IntegrationRecord:
        integration_id = payload.integration_id or f"int_{uuid.uuid4().hex}"
        data = payload.model_dump(exclude={"integration_id"})
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_integrations (
                    integration_id, platform, platform_key, display_name, enabled,
                    capability_discover, capability_monitor, capability_enumerate,
                    capability_read, capability_remediate, config_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING integration_id, platform, platform_key, display_name, enabled,
                          capability_discover, capability_monitor, capability_enumerate,
                          capability_read, capability_remediate, config_json AS config,
                          created_at, updated_at
                """,
                (
                    integration_id,
                    data["platform"],
                    data["platform_key"],
                    data["display_name"],
                    data["enabled"],
                    data["capability_discover"],
                    data["capability_monitor"],
                    data["capability_enumerate"],
                    data["capability_read"],
                    data["capability_remediate"],
                    psycopg.types.json.Json(data["config"]),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return IntegrationRecord.model_validate(row)

    def update_integration(self, integration_id: str, payload: IntegrationUpdate) -> IntegrationRecord | None:
        current = self.get_integration(integration_id)
        if current is None:
            return None
        merged = current.model_copy(update=payload.model_dump(exclude_none=True))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_integrations
                SET display_name = %s,
                    enabled = %s,
                    capability_discover = %s,
                    capability_monitor = %s,
                    capability_enumerate = %s,
                    capability_read = %s,
                    capability_remediate = %s,
                    config_json = %s::jsonb,
                    updated_at = NOW()
                WHERE integration_id = %s
                RETURNING integration_id, platform, platform_key, display_name, enabled,
                          capability_discover, capability_monitor, capability_enumerate,
                          capability_read, capability_remediate, config_json AS config,
                          created_at, updated_at
                """,
                (
                    merged.display_name,
                    merged.enabled,
                    merged.capability_discover,
                    merged.capability_monitor,
                    merged.capability_enumerate,
                    merged.capability_read,
                    merged.capability_remediate,
                    psycopg.types.json.Json(merged.config),
                    integration_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return IntegrationRecord.model_validate(row) if row else None

    def list_scopes(self, integration_id: str | None = None) -> list[ProtectedScopeRecord]:
        query = """
            SELECT scope_id, integration_id, scope_type, resource_selector, normalized_selector,
                   display_name, mode, enabled, filter_expression,
                   post_scan_policy_json AS post_scan_policy, created_at, updated_at
            FROM cp_scopes
        """
        params: tuple = ()
        if integration_id:
            query += " WHERE integration_id = %s"
            params = (integration_id,)
        query += " ORDER BY created_at"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return [ProtectedScopeRecord.model_validate(row) for row in cur.fetchall()]

    def get_scope(self, scope_id: str) -> ProtectedScopeRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT scope_id, integration_id, scope_type, resource_selector, normalized_selector,
                       display_name, mode, enabled, filter_expression,
                       post_scan_policy_json AS post_scan_policy, created_at, updated_at
                FROM cp_scopes
                WHERE scope_id = %s
                """,
                (scope_id,),
            )
            row = cur.fetchone()
            return ProtectedScopeRecord.model_validate(row) if row else None

    def create_scope(self, payload: ProtectedScopeCreate, normalized_selector: str) -> ProtectedScopeRecord:
        scope_id = payload.scope_id or f"scope_{uuid.uuid4().hex}"
        data = payload.model_dump(exclude={"scope_id"})
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_scopes (
                    scope_id, integration_id, scope_type, resource_selector, normalized_selector,
                    display_name, mode, enabled, filter_expression, post_scan_policy_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING scope_id, integration_id, scope_type, resource_selector, normalized_selector,
                          display_name, mode, enabled, filter_expression,
                          post_scan_policy_json AS post_scan_policy, created_at, updated_at
                """,
                (
                    scope_id,
                    data["integration_id"],
                    data["scope_type"],
                    data["resource_selector"],
                    normalized_selector,
                    data["display_name"],
                    data["mode"],
                    data["enabled"],
                    data["filter_expression"],
                    psycopg.types.json.Json(data["post_scan_policy"]),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return ProtectedScopeRecord.model_validate(row)

    def update_scope(
        self,
        scope_id: str,
        payload: ProtectedScopeUpdate,
        normalized_selector: str | None = None,
    ) -> ProtectedScopeRecord | None:
        current = self.get_scope(scope_id)
        if current is None:
            return None
        merged = current.model_copy(update=payload.model_dump(exclude_none=True))
        selector = normalized_selector or current.normalized_selector
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_scopes
                SET normalized_selector = %s,
                    display_name = %s,
                    mode = %s,
                    enabled = %s,
                    filter_expression = %s,
                    post_scan_policy_json = %s::jsonb,
                    updated_at = NOW()
                WHERE scope_id = %s
                RETURNING scope_id, integration_id, scope_type, resource_selector, normalized_selector,
                          display_name, mode, enabled, filter_expression,
                          post_scan_policy_json AS post_scan_policy, created_at, updated_at
                """,
                (
                    selector,
                    merged.display_name,
                    merged.mode,
                    merged.enabled,
                    merged.filter_expression,
                    psycopg.types.json.Json(merged.post_scan_policy),
                    scope_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return ProtectedScopeRecord.model_validate(row) if row else None
