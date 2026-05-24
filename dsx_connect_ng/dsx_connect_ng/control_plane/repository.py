from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid

from dsx_connect_ng.control_plane.models import (
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
