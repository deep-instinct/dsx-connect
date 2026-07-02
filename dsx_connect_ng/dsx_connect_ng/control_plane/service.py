from __future__ import annotations

from fastapi import HTTPException, status
from pydantic import ValidationError

from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config, parse_policy_runtime_config
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


def normalize_selector(scope_type: str, selector: str) -> str:
    value = selector.strip()
    if scope_type == "identity":
        return value
    parts = [part for part in value.replace("\\", "/").split("/") if part]
    return "/" + "/".join(parts)


def selectors_overlap(scope_type: str, left: str, right: str) -> bool:
    if scope_type == "identity":
        return left == right
    if left == right:
        return True
    left_prefix = left.rstrip("/") + "/"
    right_prefix = right.rstrip("/") + "/"
    return left.startswith(right_prefix) or right.startswith(left_prefix)


class ControlPlaneService:
    def __init__(self, repo: ControlPlaneRepository) -> None:
        self.repo = repo

    def _validate_integration_config(self, config: dict) -> None:
        try:
            parse_integration_runtime_config(config)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_integration_runtime_config",
                    "errors": exc.errors(),
                },
            ) from exc

    def _validate_scope_policy(self, policy: dict) -> None:
        try:
            parse_policy_runtime_config(policy)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "invalid_scope_policy_config",
                    "errors": exc.errors(),
                },
            ) from exc

    def list_integrations(self) -> list[IntegrationRecord]:
        return self.repo.list_integrations()

    def get_integration_or_404(self, integration_id: str) -> IntegrationRecord:
        row = self.repo.get_integration(integration_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration_not_found")
        return row

    def create_integration(self, payload: IntegrationCreate) -> IntegrationRecord:
        self._validate_integration_config(payload.config)
        for existing in self.repo.list_integrations():
            if existing.platform == payload.platform and existing.platform_key == payload.platform_key:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="integration_platform_key_conflict",
                )
        return self.repo.create_integration(payload)

    def update_integration(self, integration_id: str, payload: IntegrationUpdate) -> IntegrationRecord:
        self.get_integration_or_404(integration_id)
        if payload.config is not None:
            self._validate_integration_config(payload.config)
        row = self.repo.update_integration(integration_id, payload)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration_not_found")
        return row

    def _integration_for_connector_registration(self, payload: ConnectorInstanceRegister) -> IntegrationRecord:
        if payload.integration_id:
            integration = self.get_integration_or_404(payload.integration_id)
            if integration.platform != payload.platform or integration.platform_key != payload.platform_key:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "connector_integration_mismatch",
                        "integration_id": integration.integration_id,
                        "integration_platform": integration.platform,
                        "integration_platform_key": integration.platform_key,
                    },
                )
            return integration

        for existing in self.repo.list_integrations():
            if existing.platform == payload.platform and existing.platform_key == payload.platform_key:
                return existing

        return self.repo.create_integration(
            IntegrationCreate(
                platform=payload.platform,
                platform_key=payload.platform_key,
                display_name=payload.display_name or payload.connector_name,
                capability_discover=bool(payload.capabilities.get("discover", False)),
                capability_monitor=bool(payload.capabilities.get("events", payload.capabilities.get("monitor", False))),
                capability_enumerate=bool(payload.capabilities.get("enumerate", payload.capabilities.get("discover", False))),
                capability_read=bool(payload.capabilities.get("read", False)),
                capability_remediate=bool(payload.capabilities.get("remediate", False)),
                config={},
            )
        )

    def register_connector_instance(self, payload: ConnectorInstanceRegister) -> ConnectorInstanceRecord:
        integration = self._integration_for_connector_registration(payload)
        return self.repo.upsert_connector_instance(payload, integration_id=integration.integration_id)

    def list_connector_instances(self, integration_id: str | None = None) -> list[ConnectorInstanceRecord]:
        if integration_id:
            self.get_integration_or_404(integration_id)
        return self.repo.list_connector_instances(integration_id=integration_id)

    def get_connector_instance_or_404(self, connector_instance_id: str) -> ConnectorInstanceRecord:
        row = self.repo.get_connector_instance(connector_instance_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connector_instance_not_found")
        return row

    def heartbeat_connector_instance(
        self,
        connector_instance_id: str,
        payload: ConnectorInstanceHeartbeat,
    ) -> ConnectorInstanceRecord:
        row = self.repo.update_connector_instance_heartbeat(connector_instance_id, payload)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connector_instance_not_found")
        return row

    def list_scopes(self, integration_id: str | None = None) -> list[ProtectedScopeRecord]:
        if integration_id:
            self.get_integration_or_404(integration_id)
        return self.repo.list_scopes(integration_id=integration_id)

    def get_scope_or_404(self, scope_id: str) -> ProtectedScopeRecord:
        row = self.repo.get_scope(scope_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scope_not_found")
        return row

    def _validate_overlap(
        self,
        *,
        integration_id: str,
        scope_type: str,
        normalized_selector: str,
        exclude_scope_id: str | None = None,
    ) -> None:
        for existing in self.repo.list_scopes(integration_id=integration_id):
            if exclude_scope_id and existing.scope_id == exclude_scope_id:
                continue
            if existing.scope_type != scope_type:
                continue
            if selectors_overlap(scope_type, existing.normalized_selector, normalized_selector):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "scope_overlap",
                        "conflicting_scope_id": existing.scope_id,
                        "integration_id": integration_id,
                    },
                )

    def create_scope(self, payload: ProtectedScopeCreate) -> ProtectedScopeRecord:
        self.get_integration_or_404(payload.integration_id)
        self._validate_scope_policy(payload.post_scan_policy)
        normalized_selector = normalize_selector(payload.scope_type, payload.resource_selector)
        self._validate_overlap(
            integration_id=payload.integration_id,
            scope_type=payload.scope_type,
            normalized_selector=normalized_selector,
        )
        return self.repo.create_scope(payload, normalized_selector=normalized_selector)

    def update_scope(self, scope_id: str, payload: ProtectedScopeUpdate) -> ProtectedScopeRecord:
        current = self.get_scope_or_404(scope_id)
        if payload.post_scan_policy is not None:
            self._validate_scope_policy(payload.post_scan_policy)
        self._validate_overlap(
            integration_id=current.integration_id,
            scope_type=current.scope_type,
            normalized_selector=current.normalized_selector,
            exclude_scope_id=scope_id,
        )
        row = self.repo.update_scope(scope_id, payload, normalized_selector=current.normalized_selector)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scope_not_found")
        return row

    def match_scope(
        self,
        *,
        integration_id: str,
        scope_type: str,
        resource_selector: str,
    ) -> ProtectedScopeRecord | None:
        self.get_integration_or_404(integration_id)
        normalized_selector = normalize_selector(scope_type, resource_selector)
        candidates = [
            scope
            for scope in self.repo.list_scopes(integration_id=integration_id)
            if scope.enabled and scope.scope_type == scope_type
        ]
        if scope_type == "identity":
            for scope in candidates:
                if scope.normalized_selector == normalized_selector:
                    return scope
            return None

        # Longest-prefix match is deterministic when overlap invariants are respected.
        best_match: ProtectedScopeRecord | None = None
        for scope in candidates:
            selector = scope.normalized_selector.rstrip("/")
            prefix = selector + "/"
            if normalized_selector == selector or normalized_selector.startswith(prefix):
                if best_match is None or len(scope.normalized_selector) > len(best_match.normalized_selector):
                    best_match = scope
        return best_match
