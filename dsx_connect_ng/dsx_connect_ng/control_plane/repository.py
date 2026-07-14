from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import uuid

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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ControlPlaneRepository(ABC):
    @abstractmethod
    def list_integrations(self) -> list[IntegrationRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_integration(self, integration_id: str) -> IntegrationRecord | None:
        raise NotImplementedError

    @abstractmethod
    def create_integration(self, payload: IntegrationCreate) -> IntegrationRecord:
        raise NotImplementedError

    @abstractmethod
    def update_integration(self, integration_id: str, payload: IntegrationUpdate) -> IntegrationRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_connector_instances(self, integration_id: str | None = None) -> list[ConnectorInstanceRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstanceRecord | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_connector_instance(
        self,
        payload: ConnectorInstanceRegister,
        *,
        integration_id: str,
    ) -> ConnectorInstanceRecord:
        raise NotImplementedError

    @abstractmethod
    def update_connector_instance_heartbeat(
        self,
        connector_instance_id: str,
        payload: ConnectorInstanceHeartbeat,
    ) -> ConnectorInstanceRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_scopes(self, integration_id: str | None = None) -> list[ProtectedScopeRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_scope(self, scope_id: str) -> ProtectedScopeRecord | None:
        raise NotImplementedError

    @abstractmethod
    def create_scope(self, payload: ProtectedScopeCreate, normalized_selector: str) -> ProtectedScopeRecord:
        raise NotImplementedError

    @abstractmethod
    def update_scope(
        self,
        scope_id: str,
        payload: ProtectedScopeUpdate,
        normalized_selector: str | None = None,
    ) -> ProtectedScopeRecord | None:
        raise NotImplementedError


class InMemoryControlPlaneRepository(ControlPlaneRepository):
    def __init__(self) -> None:
        self._integrations: dict[str, IntegrationRecord] = {}
        self._connector_instances: dict[str, ConnectorInstanceRecord] = {}
        self._scopes: dict[str, ProtectedScopeRecord] = {}

    def list_integrations(self) -> list[IntegrationRecord]:
        return sorted(self._integrations.values(), key=lambda row: row.created_at)

    def get_integration(self, integration_id: str) -> IntegrationRecord | None:
        return self._integrations.get(integration_id)

    def create_integration(self, payload: IntegrationCreate) -> IntegrationRecord:
        integration_id = payload.integration_id or f"int_{uuid.uuid4().hex}"
        row = IntegrationRecord(integration_id=integration_id, **payload.model_dump(exclude={"integration_id"}))
        self._integrations[integration_id] = row
        return row

    def update_integration(self, integration_id: str, payload: IntegrationUpdate) -> IntegrationRecord | None:
        current = self._integrations.get(integration_id)
        if current is None:
            return None
        merged = current.model_copy(
            update={
                **payload.model_dump(exclude_none=True),
                "updated_at": utcnow(),
            }
        )
        self._integrations[integration_id] = merged
        return merged

    def list_connector_instances(self, integration_id: str | None = None) -> list[ConnectorInstanceRecord]:
        rows = self._connector_instances.values()
        if integration_id:
            rows = [row for row in rows if row.integration_id == integration_id]
        return sorted(rows, key=lambda row: row.first_seen_at)

    def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstanceRecord | None:
        return self._connector_instances.get(connector_instance_id)

    def upsert_connector_instance(
        self,
        payload: ConnectorInstanceRegister,
        *,
        integration_id: str,
    ) -> ConnectorInstanceRecord:
        now = utcnow()
        connector_instance_id = payload.connector_instance_id or f"conn_{uuid.uuid4().hex}"
        expires_at = now + timedelta(seconds=payload.lease_seconds)
        current = self._connector_instances.get(connector_instance_id)
        if current is None:
            row = ConnectorInstanceRecord(
                connector_instance_id=connector_instance_id,
                integration_id=integration_id,
                first_seen_at=now,
                last_seen_at=now,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
                **payload.model_dump(exclude={"connector_instance_id", "display_name", "integration_id"}),
            )
        else:
            row = current.model_copy(
                update={
                    **payload.model_dump(exclude={"connector_instance_id", "display_name", "integration_id"}),
                    "integration_id": integration_id,
                    "last_seen_at": now,
                    "expires_at": expires_at,
                    "updated_at": now,
                }
            )
        self._connector_instances[connector_instance_id] = row
        return row

    def update_connector_instance_heartbeat(
        self,
        connector_instance_id: str,
        payload: ConnectorInstanceHeartbeat,
    ) -> ConnectorInstanceRecord | None:
        current = self._connector_instances.get(connector_instance_id)
        if current is None:
            return None
        now = utcnow()
        lease_seconds = payload.lease_seconds or current.lease_seconds
        update = {
            "last_seen_at": now,
            "expires_at": now + timedelta(seconds=lease_seconds),
            "updated_at": now,
            "lease_seconds": lease_seconds,
        }
        if payload.health is not None:
            update["health"] = payload.health
        if payload.connector_version is not None:
            update["connector_version"] = payload.connector_version
        if payload.capabilities is not None:
            update["capabilities"] = payload.capabilities
        if payload.labels is not None:
            update["labels"] = payload.labels
        merged = current.model_copy(update=update)
        self._connector_instances[connector_instance_id] = merged
        return merged

    def list_scopes(self, integration_id: str | None = None) -> list[ProtectedScopeRecord]:
        rows = self._scopes.values()
        if integration_id:
            rows = [row for row in rows if row.integration_id == integration_id]
        return sorted(rows, key=lambda row: row.created_at)

    def get_scope(self, scope_id: str) -> ProtectedScopeRecord | None:
        return self._scopes.get(scope_id)

    def create_scope(self, payload: ProtectedScopeCreate, normalized_selector: str) -> ProtectedScopeRecord:
        scope_id = payload.scope_id or f"scope_{uuid.uuid4().hex}"
        row = ProtectedScopeRecord(
            scope_id=scope_id,
            normalized_selector=normalized_selector,
            **payload.model_dump(exclude={"scope_id"}),
        )
        self._scopes[scope_id] = row
        return row

    def update_scope(
        self,
        scope_id: str,
        payload: ProtectedScopeUpdate,
        normalized_selector: str | None = None,
    ) -> ProtectedScopeRecord | None:
        current = self._scopes.get(scope_id)
        if current is None:
            return None
        update = {
            **payload.model_dump(exclude_none=True),
            "updated_at": utcnow(),
        }
        if normalized_selector is not None:
            update["normalized_selector"] = normalized_selector
        merged = current.model_copy(update=update)
        self._scopes[scope_id] = merged
        return merged
