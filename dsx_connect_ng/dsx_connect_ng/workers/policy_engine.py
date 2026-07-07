from __future__ import annotations

from typing import Any

from typing import Awaitable, Callable

from dsx_connect_ng.control_plane.config_models import PolicyRuntimeConfig, resolve_policy_runtime_config
from dsx_connect_ng.jobs.contracts import PolicyEvaluationRequested
from dsx_connect_ng.jobs.models import (
    ContentPreservationDecision,
    DeliveryDispatchDecision,
    PolicyDecision,
    PolicyHandoffDecision,
    PolicyHandoffRequest,
    PolicyStageResult,
    StageApplicabilityDecision,
    StageResultDeliveryPolicy,
)


PolicyEngine = Callable[[PolicyHandoffRequest], Awaitable[PolicyHandoffDecision]]
LegacyPolicyEvaluator = Callable[[PolicyEvaluationRequested], Awaitable[PolicyDecision]]


def _extract_item_payload(handoff: PolicyHandoffRequest) -> dict:
    return handoff.item_payload or {}


def _extract_policy_runtime_config(handoff: PolicyHandoffRequest) -> PolicyRuntimeConfig:
    context = handoff.policy_context or {}
    resolved = context.get("resolved_policy")
    if resolved:
        return PolicyRuntimeConfig.model_validate(resolved)
    integration_config = context.get("integration_config") or {}
    scope_policy = context.get("scope_policy") or {}
    return resolve_policy_runtime_config(integration_config, scope_policy)


def _delivery_targets_from_decision(decision: PolicyDecision) -> list[dict]:
    return [decision.delivery_target] if decision.delivery_target else []


def _delivery_policy_for_scan_verdict(verdict: str) -> StageResultDeliveryPolicy:
    normalized = verdict.strip().lower()
    if normalized in {"malicious", "suspicious"}:
        return StageResultDeliveryPolicy(
            scan="malicious_only",
            remediation="all_outcomes",
            dianna="completed_only",
        )
    return StageResultDeliveryPolicy(
        scan="all_results",
        remediation="all_outcomes",
        dianna="completed_only",
    )


def _normalized_verdict(verdict: str) -> str:
    return verdict.strip().lower()


def _effective_policy_verdict(policy_config: PolicyRuntimeConfig, raw_verdict: str) -> str:
    normalized = _normalized_verdict(raw_verdict)
    if normalized in {"malicious", "suspicious", "benign"}:
        return normalized
    if normalized in {"non-compliant", "non_compliant", "noncompliant"}:
        return "malicious" if policy_config.non_compliant_treatment == "treat_as_malicious" else "benign"
    if normalized in {"not scanned", "not_scanned", "notscanned"}:
        return "malicious" if policy_config.not_scanned_treatment == "treat_as_malicious" else "benign"
    return normalized


def _default_remediation_plan_for_verdict(policy_config: PolicyRuntimeConfig, effective_verdict: str) -> dict:
    if effective_verdict != "malicious":
        return {}
    malicious_policy = policy_config.malicious_verdict
    if malicious_policy is None or malicious_policy.action == "detect_only":
        return {}
    if malicious_policy.action == "delete":
        return {"action": "delete"}
    if malicious_policy.action == "tag_only":
        return {"action": "tag_only", "tag": True}
    plan: dict[str, Any] = {"action": "quarantine"}
    if malicious_policy.quarantine_target:
        target = malicious_policy.quarantine_target
        target_data = target.model_dump(mode="json")
        target_path = (
            target.target_path
            or target.path
            or target.prefix
        )
        if target_path is not None:
            plan["targetPath"] = target_path
        plan["quarantineTarget"] = target_data
    plan["tag"] = bool(malicious_policy.tag_on_quarantine)
    return plan


def _configured_action(policy_config: PolicyRuntimeConfig, verdict_key: str) -> str:
    actions = policy_config.outcome_triggers or {}
    verdict_actions = getattr(policy_config, "verdict_actions", None) or {}
    if isinstance(verdict_actions, dict):
        value = verdict_actions.get(verdict_key)
        if value:
            return str(value)
    if verdict_key == "non_compliant" and isinstance(policy_config.non_compliance, dict):
        value = policy_config.non_compliance.get("action")
        if value:
            return str(value)
    not_scanned = getattr(policy_config, "not_scanned", None) or {}
    if verdict_key == "not_scanned" and isinstance(not_scanned, dict):
        value = not_scanned.get("action")
        if value:
            return str(value)
    if actions.get(verdict_key) is True:
        return "quarantine"
    return "detect_only"


def _remediation_plan_for_action(policy_config: PolicyRuntimeConfig, action: str, *, target_source: str) -> dict:
    normalized = str(action or "detect_only").strip().lower()
    if normalized in {"detect_only", "nothing", "none"}:
        return {}
    if normalized == "delete":
        return {"action": "delete"}
    if normalized == "tag_only":
        return {"action": "tag_only", "tag": True}

    plan: dict[str, Any] = {"action": "quarantine", "tag": True}
    target = None
    if target_source == "non_compliance" and isinstance(policy_config.non_compliance, dict):
        target = policy_config.non_compliance.get("quarantine_target") or policy_config.non_compliance.get("quarantineTarget")
    if target is None and policy_config.malicious_verdict is not None:
        target = policy_config.malicious_verdict.quarantine_target
    if target is not None:
        target_data = target.model_dump(mode="json") if hasattr(target, "model_dump") else dict(target)
        target_path = target_data.get("target_path") or target_data.get("targetPath") or target_data.get("path") or target_data.get("prefix")
        if target_path is not None:
            plan["targetPath"] = target_path
        plan["quarantineTarget"] = target_data
    return plan


def _scan_file_info(handoff: PolicyHandoffRequest) -> dict[str, Any]:
    return handoff.scan_result.file_info or {}


def _file_type_tokens(handoff: PolicyHandoffRequest) -> set[str]:
    file_info = _scan_file_info(handoff)
    file_type = str(file_info.get("file_type") or "").lower()
    object_identity = str(handoff.object_identity or "").lower()
    tokens: set[str] = set()
    if "pdf" in file_type or object_identity.endswith(".pdf"):
        tokens.add("pdf")
    if any(marker in file_type for marker in ("pe", "elf", "macho", "mach-o", "executable", "eicar")):
        tokens.update({"executables", "windows_executable"})
    if "office" in file_type:
        office_data = file_info.get("additional_office_data") or {}
        has_macro = any(bool(office_data.get(key)) for key in ("vba", "xl4_macros"))
        if has_macro:
            tokens.add("office_macro")
        elif object_identity.endswith((".doc", ".docx")) or "_doc" in object_identity:
            tokens.add("office_word")
        elif object_identity.endswith((".xls", ".xlsx")) or "_xls" in object_identity or "_xlsx" in object_identity:
            tokens.add("office_excel")
        else:
            tokens.add("office_other")
    return tokens


def _non_compliance_match(policy_config: PolicyRuntimeConfig, handoff: PolicyHandoffRequest) -> str | None:
    if not isinstance(policy_config.non_compliance, dict):
        return None
    blocked = {str(value).strip().lower() for value in policy_config.non_compliance.get("blocked_file_types", [])}
    if not blocked:
        return None
    tokens = _file_type_tokens(handoff)
    matched = sorted(blocked.intersection(tokens))
    return matched[0] if matched else None


def _targets_from_policy_config(policy_config: PolicyRuntimeConfig, fallback_targets: list[dict]) -> DeliveryDispatchDecision:
    delivery = policy_config.delivery
    if delivery is None:
        return DeliveryDispatchDecision(
            targets=fallback_targets,
            scan_targets=fallback_targets,
            remediation_targets=fallback_targets,
            dianna_targets=fallback_targets,
            workflow_summary_targets=fallback_targets,
        )
    workflow_summary_targets = (
        fallback_targets
        if delivery.workflow_summary_targets is None
        else delivery.workflow_summary_targets
    )
    return DeliveryDispatchDecision(
        targets=workflow_summary_targets,
        scan_targets=fallback_targets if delivery.scan_targets is None else delivery.scan_targets,
        remediation_targets=fallback_targets if delivery.remediation_targets is None else delivery.remediation_targets,
        dianna_targets=fallback_targets if delivery.dianna_targets is None else delivery.dianna_targets,
        workflow_summary_targets=workflow_summary_targets,
        scan_targets_configured=delivery.scan_targets is not None,
        remediation_targets_configured=delivery.remediation_targets is not None,
        dianna_targets_configured=delivery.dianna_targets is not None,
        workflow_summary_targets_configured=delivery.workflow_summary_targets is not None,
    )


def _content_preservation_for_verdict(policy_config: PolicyRuntimeConfig, verdict: str) -> ContentPreservationDecision:
    mode_map = policy_config.content_preservation_mode_by_verdict or {}
    mode = mode_map.get(verdict)
    if mode is None:
        return ContentPreservationDecision(mode="none", reason="no_preservation_policy")
    reason = "policy_content_preservation"
    if mode == "none":
        reason = "no_later_stage_requires_content"
    return ContentPreservationDecision(mode=mode, reason=reason)


def _build_stub_handoff_decision(
    handoff: PolicyHandoffRequest,
    decision: PolicyDecision,
    *,
    effective_verdict_override: str | None = None,
    policy_reason: str | None = None,
) -> PolicyHandoffDecision:
    verdict = handoff.scan_result.verdict
    policy_config = _extract_policy_runtime_config(handoff)
    effective_verdict = effective_verdict_override or _effective_policy_verdict(policy_config, verdict)
    remediation = (
        StageApplicabilityDecision(state="requested", details={"remediation_plan": decision.remediation_plan})
        if decision.remediation_plan
        else StageApplicabilityDecision(
            state="skipped",
            reason="benign_verdict" if effective_verdict == "benign" else "remediation_not_configured",
        )
    )
    delivery = _targets_from_policy_config(policy_config, _delivery_targets_from_decision(decision))
    request_now = bool(
        (delivery.workflow_summary_targets or delivery.targets)
        and not decision.remediation_plan
        and not decision.wait_for_dianna_before_delivery
    )
    delivery = delivery.model_copy(
        update={
            "request_now": request_now,
            "wait_for_dianna": decision.wait_for_dianna_before_delivery,
        }
    )
    dianna = (
        StageApplicabilityDecision(state="requested")
        if decision.request_dianna
        else StageApplicabilityDecision(
            state="skipped",
            reason="not_auto_requested",
            details={"verdict": verdict, "effective_verdict": effective_verdict} if verdict else {},
        )
    )
    return PolicyHandoffDecision(
        policy_stage_result=PolicyStageResult(
            policy_id=policy_config.policy_id,
            decision_trace={
                "engine": "stub_policy",
                "source": "policy_worker",
                "verdict": _normalized_verdict(verdict),
                "effective_verdict": effective_verdict,
                **({"policy_reason": policy_reason} if policy_reason else {}),
            }
        ),
        remediation=remediation,
        dianna=dianna,
        delivery=delivery,
        content_preservation=_content_preservation_for_verdict(policy_config, effective_verdict),
        result_delivery_policy=policy_config.result_delivery_policy or _delivery_policy_for_scan_verdict(effective_verdict),
    )


def policy_decision_from_handoff_decision(handoff: PolicyHandoffDecision) -> PolicyDecision:
    summary_targets = (
        handoff.delivery.workflow_summary_targets
        if handoff.delivery.workflow_summary_targets_configured
        else handoff.delivery.workflow_summary_targets or handoff.delivery.targets
    )
    target = summary_targets[0] if summary_targets else {}
    return PolicyDecision(
        remediation_plan=handoff.remediation.details.get("remediation_plan", {}),
        delivery_target=target,
        request_dianna=handoff.dianna.state == "requested",
        wait_for_dianna_before_delivery=handoff.delivery.wait_for_dianna,
        dianna_reason="auto_on_malicious",
        dianna_options=handoff.dianna.details,
    )


async def stub_policy_engine(handoff: PolicyHandoffRequest) -> PolicyHandoffDecision:
    item_payload = _extract_item_payload(handoff)
    policy_config = _extract_policy_runtime_config(handoff)
    effective_verdict = _effective_policy_verdict(policy_config, handoff.scan_result.verdict)
    non_compliance_reason = _non_compliance_match(policy_config, handoff)
    not_scanned_action = _configured_action(policy_config, "not_scanned")
    if non_compliance_reason and _configured_action(policy_config, "non_compliant") != "detect_only":
        effective_verdict = "malicious"
    if _normalized_verdict(handoff.scan_result.verdict) in {"not scanned", "not_scanned", "notscanned"} and not_scanned_action != "detect_only":
        effective_verdict = "malicious"
    explicit = item_payload.get("policyDecision") or item_payload.get("policy_decision")
    if explicit:
        decision = PolicyDecision.model_validate(explicit)
        return _build_stub_handoff_decision(handoff, decision)

    remediation_by_verdict = policy_config.remediation_plan_by_verdict or {}
    remediation_plan = (
        item_payload.get("remediationPlan")
        or item_payload.get("remediation_plan")
        or remediation_by_verdict.get(effective_verdict)
        or {}
    )
    if not remediation_plan and non_compliance_reason:
        remediation_plan = _remediation_plan_for_action(
            policy_config,
            _configured_action(policy_config, "non_compliant"),
            target_source="non_compliance",
        )
    if not remediation_plan and _normalized_verdict(handoff.scan_result.verdict) in {"not scanned", "not_scanned", "notscanned"}:
        remediation_plan = _remediation_plan_for_action(
            policy_config,
            not_scanned_action,
            target_source="non_compliance",
        )
    if not remediation_plan:
        remediation_plan = _default_remediation_plan_for_verdict(policy_config, effective_verdict)
    request_dianna = bool(item_payload.get("requestDianna") or item_payload.get("request_dianna"))
    if not request_dianna:
        auto_dianna = policy_config.auto_dianna_on_verdicts or []
        request_dianna = effective_verdict in auto_dianna
    wait_for_dianna = bool(
        item_payload.get("waitForDiannaBeforeDelivery")
        or item_payload.get("wait_for_dianna_before_delivery")
    )
    if request_dianna and not wait_for_dianna:
        wait_for_dianna = bool(policy_config.wait_for_dianna_on_auto_request)

    decision = PolicyDecision(
        delivery_target=item_payload.get("deliveryTarget") or item_payload.get("delivery_target") or {},
        remediation_plan=remediation_plan,
        request_dianna=request_dianna,
        wait_for_dianna_before_delivery=wait_for_dianna,
    )
    policy_reason = None
    if non_compliance_reason:
        policy_reason = f"blocked_file_type:{non_compliance_reason}"
    elif _normalized_verdict(handoff.scan_result.verdict) in {"not scanned", "not_scanned", "notscanned"} and not_scanned_action != "detect_only":
        policy_reason = "not_scanned_action"
    return _build_stub_handoff_decision(
        handoff,
        decision,
        effective_verdict_override=effective_verdict,
        policy_reason=policy_reason,
    )


async def stub_policy_evaluator(request: PolicyEvaluationRequested) -> PolicyDecision:
    handoff = request.as_policy_handoff_request()
    decision = await stub_policy_engine(handoff)
    return policy_decision_from_handoff_decision(decision)
