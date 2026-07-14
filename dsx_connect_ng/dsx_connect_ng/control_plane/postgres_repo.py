from __future__ import annotations

from contextlib import contextmanager
import threading
import uuid

import psycopg
from psycopg.rows import dict_row

from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRecord,
    ConnectorInstanceRegister,
    IntegrationCreate,
    IntegrationRecord,
    IntegrationUpdate,
    ProtectedScopeCreate,
    ProtectedScopeRecord,
    ProtectedScopeUpdate,
)
from dsx_connect_ng.control_plane.repository import ControlPlaneRepository
from dsx_connect_ng.jobs.postgres_repo import apply_schema as apply_job_schema


def apply_schema(db_url: str) -> None:
    apply_job_schema(db_url)


class PostgresControlPlaneRepository(ControlPlaneRepository):
    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self._local = threading.local()

    def _thread_connection(self):
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = psycopg.connect(self.db_url, row_factory=dict_row)
            self._local.conn = conn
        return conn

    @contextmanager
    def _connect(self):
        conn = self._thread_connection()
        try:
            yield conn
        except Exception:
            if not conn.closed:
                conn.rollback()
            raise
        else:
            if not conn.closed:
                conn.commit()

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

    def list_connector_instances(self, integration_id: str | None = None) -> list[ConnectorInstanceRecord]:
        query = """
            SELECT connector_instance_id, integration_id, platform, platform_key,
                   connector_name, connector_version, base_url,
                   capabilities_json AS capabilities, health, labels_json AS labels,
                   lease_seconds, first_seen_at, last_seen_at, expires_at,
                   created_at, updated_at
            FROM cp_connector_instances
        """
        params: tuple = ()
        if integration_id:
            query += " WHERE integration_id = %s"
            params = (integration_id,)
        query += " ORDER BY first_seen_at"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query, params)
            return [ConnectorInstanceRecord.model_validate(row) for row in cur.fetchall()]

    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstanceRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT connector_instance_id, integration_id, platform, platform_key,
                       connector_name, connector_version, base_url,
                       capabilities_json AS capabilities, health, labels_json AS labels,
                       lease_seconds, first_seen_at, last_seen_at, expires_at,
                       created_at, updated_at
                FROM cp_connector_instances
                WHERE connector_instance_id = %s
                """,
                (connector_instance_id,),
            )
            row = cur.fetchone()
            return ConnectorInstanceRecord.model_validate(row) if row else None

    def upsert_connector_instance(
        self,
        payload: ConnectorInstanceRegister,
        *,
        integration_id: str,
    ) -> ConnectorInstanceRecord:
        connector_instance_id = payload.connector_instance_id or f"conn_{uuid.uuid4().hex}"
        data = payload.model_dump(exclude={"connector_instance_id", "display_name", "integration_id"})
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cp_connector_instances (
                    connector_instance_id, integration_id, platform, platform_key,
                    connector_name, connector_version, base_url,
                    capabilities_json, health, labels_json, lease_seconds,
                    first_seen_at, last_seen_at, expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                    NOW(), NOW(), NOW() + (%s * INTERVAL '1 second')
                )
                ON CONFLICT (connector_instance_id) DO UPDATE
                SET integration_id = EXCLUDED.integration_id,
                    platform = EXCLUDED.platform,
                    platform_key = EXCLUDED.platform_key,
                    connector_name = EXCLUDED.connector_name,
                    connector_version = EXCLUDED.connector_version,
                    base_url = EXCLUDED.base_url,
                    capabilities_json = EXCLUDED.capabilities_json,
                    health = EXCLUDED.health,
                    labels_json = EXCLUDED.labels_json,
                    lease_seconds = EXCLUDED.lease_seconds,
                    last_seen_at = NOW(),
                    expires_at = NOW() + (EXCLUDED.lease_seconds * INTERVAL '1 second'),
                    updated_at = NOW()
                RETURNING connector_instance_id, integration_id, platform, platform_key,
                          connector_name, connector_version, base_url,
                          capabilities_json AS capabilities, health, labels_json AS labels,
                          lease_seconds, first_seen_at, last_seen_at, expires_at,
                          created_at, updated_at
                """,
                (
                    connector_instance_id,
                    integration_id,
                    data["platform"],
                    data["platform_key"],
                    data["connector_name"],
                    data["connector_version"],
                    data["base_url"],
                    psycopg.types.json.Json(data["capabilities"]),
                    data["health"],
                    psycopg.types.json.Json(data["labels"]),
                    data["lease_seconds"],
                    data["lease_seconds"],
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return ConnectorInstanceRecord.model_validate(row)

    def update_connector_instance_heartbeat(
        self,
        connector_instance_id: str,
        payload: ConnectorInstanceHeartbeat,
    ) -> ConnectorInstanceRecord | None:
        current = self.get_connector_instance(connector_instance_id)
        if current is None:
            return None
        lease_seconds = payload.lease_seconds or current.lease_seconds
        health = payload.health or current.health
        connector_version = payload.connector_version if payload.connector_version is not None else current.connector_version
        capabilities = payload.capabilities if payload.capabilities is not None else current.capabilities
        labels = payload.labels if payload.labels is not None else current.labels
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE cp_connector_instances
                SET health = %s,
                    connector_version = %s,
                    capabilities_json = %s::jsonb,
                    labels_json = %s::jsonb,
                    lease_seconds = %s,
                    last_seen_at = NOW(),
                    expires_at = NOW() + (%s * INTERVAL '1 second'),
                    updated_at = NOW()
                WHERE connector_instance_id = %s
                RETURNING connector_instance_id, integration_id, platform, platform_key,
                          connector_name, connector_version, base_url,
                          capabilities_json AS capabilities, health, labels_json AS labels,
                          lease_seconds, first_seen_at, last_seen_at, expires_at,
                          created_at, updated_at
                """,
                (
                    health,
                    connector_version,
                    psycopg.types.json.Json(capabilities),
                    psycopg.types.json.Json(labels),
                    lease_seconds,
                    lease_seconds,
                    connector_instance_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return ConnectorInstanceRecord.model_validate(row) if row else None

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
