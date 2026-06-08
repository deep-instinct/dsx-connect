from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from dsx_connect_ng.jobs.models import ContentSourceMode, StageResultDeliveryPolicy
from dsx_connect_ng.readers.contracts import ReaderStrategy


ProxyAuthMode = Literal["none", "static_header", "dsx_hmac"]
PolicyVerdict = Literal["benign", "suspicious", "malicious"]
PolicyRemediationAction = Literal["detect_only", "quarantine", "delete", "tag_only"]
PolicyFallbackTreatment = Literal["treat_as_benign", "treat_as_malicious"]
QuarantineCollisionStrategy = Literal["overwrite", "suffix_random", "fail"]


class ProxyReaderConfig(BaseModel):
    endpoint_url: str | None = None
    base_url: str | None = None
    connector_name: str | None = None
    auth_mode: ProxyAuthMode = "none"
    header_name: str | None = None
    header_value: str | None = None
    hmac_key_id: str | None = None
    hmac_secret: str | None = None
    timeout_seconds: float = 30.0


class ReaderConfig(BaseModel):
    default_strategy: ReaderStrategy | None = None
    proxy: ProxyReaderConfig | None = None


class RemediationCapabilitiesConfig(BaseModel):
    supports_delete: bool = False
    supports_move: bool = False
    supports_tag: bool = False
    supports_movetag: bool = False
    supports_overwrite: bool = False
    supports_metadata_preserving_move: bool = False

    def supports_action(self, action: str) -> bool:
        normalized = str(action or "nothing").strip().lower()
        if normalized == "nothing":
            return True
        if normalized == "delete":
            return self.supports_delete
        if normalized == "move":
            return self.supports_move
        if normalized == "tag":
            return self.supports_tag
        if normalized == "movetag":
            return self.supports_movetag or (self.supports_move and self.supports_tag)
        return False


class PolicyDeliveryTargetsConfig(BaseModel):
    scan_targets: list[dict[str, Any]] | None = None
    remediation_targets: list[dict[str, Any]] | None = None
    dianna_targets: list[dict[str, Any]] | None = None
    workflow_summary_targets: list[dict[str, Any]] | None = None


class QuarantineTargetConfig(BaseModel):
    path: str | None = None
    prefix: str | None = None
    target_path: str | None = None
    repository: str | None = None
    preserve_relative_path: bool = False
    collision_strategy: QuarantineCollisionStrategy = "suffix_random"
    suffix_length: int = Field(default=10, ge=1, le=64)


class MaliciousVerdictPolicyConfig(BaseModel):
    action: PolicyRemediationAction = "detect_only"
    quarantine_target: QuarantineTargetConfig | None = None
    tag_on_quarantine: bool = True


class PolicyRuntimeConfig(BaseModel):
    policy_id: str | None = None
    auto_dianna_on_verdicts: list[PolicyVerdict] | None = None
    wait_for_dianna_on_auto_request: bool | None = None
    malicious_verdict: MaliciousVerdictPolicyConfig | None = None
    non_compliant_treatment: PolicyFallbackTreatment | None = None
    not_scanned_treatment: PolicyFallbackTreatment | None = None
    remediation_plan_by_verdict: dict[PolicyVerdict, dict[str, Any]] | None = None
    result_delivery_policy: StageResultDeliveryPolicy | None = None
    delivery: PolicyDeliveryTargetsConfig | None = None
    content_preservation_mode_by_verdict: dict[PolicyVerdict, ContentSourceMode] | None = None


class IntegrationRuntimeConfig(BaseModel):
    reader: ReaderConfig | None = None
    reader_strategy: ReaderStrategy | None = None
    remediation: RemediationCapabilitiesConfig | None = None
    policy: PolicyRuntimeConfig | None = None


def resolve_remediation_capabilities(config: dict | None, *, default_enabled: bool = False) -> RemediationCapabilitiesConfig:
    runtime = parse_integration_runtime_config(config)
    if runtime.remediation is not None:
        return runtime.remediation
    return RemediationCapabilitiesConfig(
        supports_delete=default_enabled,
        supports_move=default_enabled,
        supports_tag=default_enabled,
        supports_movetag=default_enabled,
    )


def parse_integration_runtime_config(config: dict | None) -> IntegrationRuntimeConfig:
    return IntegrationRuntimeConfig.model_validate(config or {})


def parse_policy_runtime_config(config: dict | None) -> PolicyRuntimeConfig:
    return PolicyRuntimeConfig.model_validate(config or {})


def resolve_policy_runtime_config(
    integration_config: dict | None,
    scope_policy: dict | None = None,
) -> PolicyRuntimeConfig:
    integration_runtime = parse_integration_runtime_config(integration_config)
    integration_policy = integration_runtime.policy or PolicyRuntimeConfig()
    scope_runtime = parse_policy_runtime_config(scope_policy)

    def _resolve(field_name: str):
        scope_value = getattr(scope_runtime, field_name)
        if scope_value is not None:
            return scope_value
        return getattr(integration_policy, field_name)

    return PolicyRuntimeConfig(
        policy_id=_resolve("policy_id"),
        auto_dianna_on_verdicts=_resolve("auto_dianna_on_verdicts"),
        wait_for_dianna_on_auto_request=_resolve("wait_for_dianna_on_auto_request"),
        malicious_verdict=_resolve("malicious_verdict"),
        non_compliant_treatment=_resolve("non_compliant_treatment"),
        not_scanned_treatment=_resolve("not_scanned_treatment"),
        remediation_plan_by_verdict=_resolve("remediation_plan_by_verdict"),
        result_delivery_policy=_resolve("result_delivery_policy"),
        delivery=_resolve("delivery"),
        content_preservation_mode_by_verdict=_resolve("content_preservation_mode_by_verdict"),
    )
