from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlparse, urlunparse

from fastapi import HTTPException, status
from pydantic import ValidationError

from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config, parse_policy_runtime_config
from dsx_connect_ng.control_plane.models import (
    ConnectorInstanceHeartbeat,
    ConnectorInstanceRecord,
    ConnectorInstanceRegister,
    GatewayApplicationCreate,
    GatewayApplicationIdentityBinding,
    GatewayApplicationRecord,
    GatewayApplicationUpdate,
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


def _static_bearer_token(binding: GatewayApplicationIdentityBinding) -> str | None:
    if binding.provider != "static_bearer":
        return None
    token = (binding.token or "").strip()
    return token or None


def normalize_registered_connector_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"0.0.0.0", "::"}:
        return base_url
    netloc = "127.0.0.1"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


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

    def _normalize_gateway_application_identity_bindings(
        self,
        payload: GatewayApplicationCreate | GatewayApplicationUpdate,
    ) -> GatewayApplicationCreate | GatewayApplicationUpdate:
        bindings = payload.identity_bindings
        if bindings is None:
            return payload
        normalized_bindings: list[GatewayApplicationIdentityBinding] = []
        for binding in bindings:
            data = binding.model_dump()
            if isinstance(data.get("token"), str):
                data["token"] = data["token"].strip() or None
            normalized_bindings.append(GatewayApplicationIdentityBinding.model_validate(data))
        payload_data = payload.model_dump(exclude_none=False)
        payload_data["identity_bindings"] = normalized_bindings
        return type(payload).model_validate(payload_data)

    def _validate_gateway_application_static_token_uniqueness(
        self,
        payload: GatewayApplicationCreate | GatewayApplicationUpdate,
        *,
        exclude_application_id: str | None = None,
    ) -> None:
        bindings = payload.identity_bindings
        if bindings is None:
            return

        tokens: list[str] = []
        for binding in bindings:
            token = _static_bearer_token(binding)
            if token is not None:
                tokens.append(token)

        if not tokens:
            return

        seen: set[str] = set()
        duplicates: set[str] = set()
        for token in tokens:
            if token in seen:
                duplicates.add(token)
            seen.add(token)
        if duplicates:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "duplicate_gateway_application_static_token",
                    "tokens": sorted(duplicates),
                },
            )

        conflict_app_ids: set[str] = set()
        conflict_tokens: set[str] = set()
        for token in seen:
            for application in self.repo.list_gateway_applications():
                if exclude_application_id and application.application_id == exclude_application_id:
                    continue
                for binding in application.identity_bindings:
                    if _static_bearer_token(binding) == token:
                        conflict_app_ids.add(application.application_id)
                        conflict_tokens.add(token)
                        break
                if token in conflict_tokens:
                    break

        if conflict_app_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "gateway_application_token_conflict",
                    "application_ids": sorted(conflict_app_ids),
                    "tokens": sorted(conflict_tokens),
                },
            )

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

    def _default_reader_config_for_connector(self, payload: ConnectorInstanceRegister) -> dict:
        normalized_base_url = normalize_registered_connector_base_url(payload.base_url).rstrip("/")
        return {
            "default_strategy": "proxy",
            "proxy": {
                "endpoint_url": f"{normalized_base_url}/read_file",
                "base_url": normalized_base_url,
                "connector_name": payload.connector_name,
            },
        }

    def _default_delivery_config_for_connector(self, payload: ConnectorInstanceRegister) -> dict:
        normalized_base_url = normalize_registered_connector_base_url(payload.base_url).rstrip("/")
        return {
            "proxy": {
                "endpoint_url": f"{normalized_base_url}/write_file",
                "base_url": normalized_base_url,
                "connector_name": payload.connector_name,
            },
        }

    def _ensure_reader_config_for_connector_registration(
        self,
        integration: IntegrationRecord,
        payload: ConnectorInstanceRegister,
    ) -> IntegrationRecord:
        needs_reader = bool(payload.capabilities.get("read", False))
        needs_delivery = bool(payload.capabilities.get("write", False))
        if not needs_reader and not needs_delivery:
            return integration

        runtime = parse_integration_runtime_config(integration.config)
        has_reader = runtime.reader is not None or runtime.reader_strategy is not None
        has_delivery = runtime.delivery is not None
        if (not needs_reader or has_reader) and (not needs_delivery or has_delivery):
            return integration

        config = deepcopy(integration.config)
        if needs_reader and not has_reader:
            config["reader"] = self._default_reader_config_for_connector(payload)
        if needs_delivery and not has_delivery:
            config["delivery"] = self._default_delivery_config_for_connector(payload)
        self._validate_integration_config(config)
        return self.update_integration(integration.integration_id, IntegrationUpdate(config=config))

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
            return self._ensure_reader_config_for_connector_registration(integration, payload)

        for existing in self.repo.list_integrations():
            if existing.platform == payload.platform and existing.platform_key == payload.platform_key:
                return self._ensure_reader_config_for_connector_registration(existing, payload)

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
                config={
                    **(
                        {"reader": self._default_reader_config_for_connector(payload)}
                        if bool(payload.capabilities.get("read", False))
                        else {}
                    ),
                    **(
                        {"delivery": self._default_delivery_config_for_connector(payload)}
                        if bool(payload.capabilities.get("write", False))
                        else {}
                    ),
                },
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
        integration = self.get_integration_or_404(row.integration_id)
        self._ensure_reader_config_for_connector_registration(
            integration,
            ConnectorInstanceRegister(
                connector_instance_id=row.connector_instance_id,
                integration_id=row.integration_id,
                platform=row.platform,
                platform_key=row.platform_key,
                connector_name=row.connector_name,
                connector_version=row.connector_version,
                base_url=row.base_url,
                capabilities=row.capabilities,
                health=row.health,
                labels=row.labels,
                lease_seconds=row.lease_seconds,
            ),
        )
        return row

    def list_gateway_applications(self) -> list[GatewayApplicationRecord]:
        return self.repo.list_gateway_applications()

    def get_gateway_application_or_404(self, application_id: str) -> GatewayApplicationRecord:
        row = self.repo.get_gateway_application(application_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="gateway_application_not_found")
        return row

    def _validate_gateway_application(self, payload: GatewayApplicationCreate | GatewayApplicationUpdate) -> None:
        grants = payload.grants
        if grants is None:
            return
        valid_actions = {"discover", "submit", "status"}
        for grant in grants:
            unknown = set(grant.actions) - valid_actions
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "code": "invalid_gateway_application_grant_actions",
                        "actions": sorted(unknown),
                    },
                )

    def _normalize_gateway_application_create(self, payload: GatewayApplicationCreate) -> GatewayApplicationCreate:
        data = payload.model_dump()
        data["display_name"] = (payload.display_name or payload.application_id).strip() or payload.application_id
        normalized = GatewayApplicationCreate.model_validate(data)
        return self._normalize_gateway_application_identity_bindings(normalized)

    def _normalize_gateway_application_update(
        self,
        application_id: str,
        payload: GatewayApplicationUpdate,
    ) -> GatewayApplicationUpdate:
        update = payload.model_dump(exclude_unset=True)
        if "display_name" in update:
            display_name = (update["display_name"] or "").strip()
            update["display_name"] = display_name or application_id
        normalized = GatewayApplicationUpdate.model_validate(update)
        return self._normalize_gateway_application_identity_bindings(normalized)

    def create_gateway_application(self, payload: GatewayApplicationCreate) -> GatewayApplicationRecord:
        payload = self._normalize_gateway_application_create(payload)
        self._validate_gateway_application(payload)
        self._validate_gateway_application_static_token_uniqueness(payload)
        if self.repo.get_gateway_application(payload.application_id) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="gateway_application_conflict")
        return self.repo.create_gateway_application(payload)

    def update_gateway_application(
        self,
        application_id: str,
        payload: GatewayApplicationUpdate,
    ) -> GatewayApplicationRecord:
        self.get_gateway_application_or_404(application_id)
        payload = self._normalize_gateway_application_update(application_id, payload)
        self._validate_gateway_application(payload)
        self._validate_gateway_application_static_token_uniqueness(payload, exclude_application_id=application_id)
        row = self.repo.update_gateway_application(application_id, payload)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="gateway_application_not_found")
        return row

    def find_gateway_application_by_static_token(self, token: str) -> GatewayApplicationRecord | None:
        normalized_token = token.strip()
        if not normalized_token:
            return None
        matches: list[GatewayApplicationRecord] = []
        for application in self.repo.list_gateway_applications():
            if not application.enabled:
                continue
            for binding in application.identity_bindings:
                if _static_bearer_token(binding) == normalized_token:
                    matches.append(application)
                    break
        if len(matches) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "gateway_application_token_conflict",
                    "application_ids": sorted({application.application_id for application in matches}),
                    "token": normalized_token,
                },
            )
        return matches[0] if matches else None

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
