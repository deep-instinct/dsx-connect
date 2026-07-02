from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from dsx_connect_ng.control_plane.config_models import RemediationCapabilitiesConfig, resolve_remediation_capabilities


ScopeType = Literal["path", "identity"]
ScopeMode = Literal["monitor", "full_scan"]
ConnectorHealth = Literal["unknown", "healthy", "degraded", "unhealthy"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationBase(BaseModel):
    platform: str = Field(min_length=1)
    platform_key: str = Field(min_length=1, description="Stable tenant/account/project identifier for the integration.")
    display_name: str = Field(min_length=1)
    enabled: bool = True
    capability_discover: bool = True
    capability_monitor: bool = True
    capability_enumerate: bool = False
    capability_read: bool = False
    capability_remediate: bool = False
    config: dict = Field(default_factory=dict)

    @computed_field
    @property
    def remediation_capabilities(self) -> RemediationCapabilitiesConfig:
        return resolve_remediation_capabilities(
            self.config,
            default_enabled=self.capability_remediate,
        )


class IntegrationCreate(IntegrationBase):
    integration_id: str | None = None


class IntegrationUpdate(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    capability_discover: bool | None = None
    capability_monitor: bool | None = None
    capability_enumerate: bool | None = None
    capability_read: bool | None = None
    capability_remediate: bool | None = None
    config: dict | None = None


class IntegrationRecord(IntegrationBase):
    integration_id: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ConnectorInstanceBase(BaseModel):
    integration_id: str | None = None
    platform: str = Field(min_length=1)
    platform_key: str = Field(min_length=1)
    connector_name: str = Field(min_length=1)
    connector_version: str | None = None
    base_url: str = Field(min_length=1)
    capabilities: dict = Field(default_factory=dict)
    health: ConnectorHealth = "unknown"
    labels: dict = Field(default_factory=dict)
    lease_seconds: int = Field(default=120, ge=15, le=86400)


class ConnectorInstanceRegister(ConnectorInstanceBase):
    connector_instance_id: str | None = None
    display_name: str | None = None


class ConnectorInstanceHeartbeat(BaseModel):
    health: ConnectorHealth | None = None
    capabilities: dict | None = None
    labels: dict | None = None
    lease_seconds: int | None = Field(default=None, ge=15, le=86400)


class ConnectorInstanceRecord(ConnectorInstanceBase):
    connector_instance_id: str
    integration_id: str
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(default_factory=lambda: utcnow() + timedelta(seconds=120))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProtectedScopeBase(BaseModel):
    integration_id: str = Field(min_length=1)
    scope_type: ScopeType
    resource_selector: str = Field(min_length=1, description="Canonical identity or canonical path/prefix.")
    display_name: str = Field(min_length=1)
    mode: ScopeMode
    enabled: bool = True
    filter_expression: str | None = None
    post_scan_policy: dict = Field(default_factory=dict)


class ProtectedScopeCreate(ProtectedScopeBase):
    scope_id: str | None = None


class ProtectedScopeUpdate(BaseModel):
    display_name: str | None = None
    mode: ScopeMode | None = None
    enabled: bool | None = None
    filter_expression: str | None = None
    post_scan_policy: dict | None = None


class ProtectedScopeRecord(ProtectedScopeBase):
    scope_id: str
    normalized_selector: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
