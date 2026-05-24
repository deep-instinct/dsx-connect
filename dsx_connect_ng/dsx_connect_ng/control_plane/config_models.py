from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from dsx_connect_ng.jobs.models import ContentSourceMode, StageResultDeliveryPolicy
from dsx_connect_ng.readers.contracts import ReaderStrategy


ProxyAuthMode = Literal["none", "static_header", "dsx_hmac"]
PolicyVerdict = Literal["benign", "suspicious", "malicious"]


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


class PolicyDeliveryTargetsConfig(BaseModel):
    scan_targets: list[dict[str, Any]] | None = None
    remediation_targets: list[dict[str, Any]] | None = None
    dianna_targets: list[dict[str, Any]] | None = None
    workflow_summary_targets: list[dict[str, Any]] | None = None


class PolicyRuntimeConfig(BaseModel):
    policy_id: str | None = None
    auto_dianna_on_verdicts: list[PolicyVerdict] | None = None
    wait_for_dianna_on_auto_request: bool | None = None
    remediation_plan_by_verdict: dict[PolicyVerdict, dict[str, Any]] | None = None
    result_delivery_policy: StageResultDeliveryPolicy | None = None
    delivery: PolicyDeliveryTargetsConfig | None = None
    content_preservation_mode_by_verdict: dict[PolicyVerdict, ContentSourceMode] | None = None


class IntegrationRuntimeConfig(BaseModel):
    reader: ReaderConfig | None = None
    reader_strategy: ReaderStrategy | None = None
    policy: PolicyRuntimeConfig | None = None


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
        remediation_plan_by_verdict=_resolve("remediation_plan_by_verdict"),
        result_delivery_policy=_resolve("result_delivery_policy"),
        delivery=_resolve("delivery"),
        content_preservation_mode_by_verdict=_resolve("content_preservation_mode_by_verdict"),
    )
