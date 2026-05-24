from __future__ import annotations

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
    return DeliveryDispatchDecision(
        targets=delivery.workflow_summary_targets or fallback_targets,
        scan_targets=delivery.scan_targets or fallback_targets,
        remediation_targets=delivery.remediation_targets or fallback_targets,
        dianna_targets=delivery.dianna_targets or fallback_targets,
        workflow_summary_targets=delivery.workflow_summary_targets or fallback_targets,
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


def _build_stub_handoff_decision(handoff: PolicyHandoffRequest, decision: PolicyDecision) -> PolicyHandoffDecision:
    verdict = handoff.scan_result.verdict
    normalized_verdict = _normalized_verdict(verdict)
    policy_config = _extract_policy_runtime_config(handoff)
    remediation = (
        StageApplicabilityDecision(state="requested", details={"remediation_plan": decision.remediation_plan})
        if decision.remediation_plan
        else StageApplicabilityDecision(
            state="skipped",
            reason="benign_verdict" if verdict.strip().lower() == "benign" else "remediation_not_configured",
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
            details={"verdict": verdict} if verdict else {},
        )
    )
    return PolicyHandoffDecision(
        policy_stage_result=PolicyStageResult(
            policy_id=policy_config.policy_id,
            decision_trace={"engine": "stub_policy", "source": "scan_worker_inline", "verdict": normalized_verdict}
        ),
        remediation=remediation,
        dianna=dianna,
        delivery=delivery,
        content_preservation=_content_preservation_for_verdict(policy_config, normalized_verdict),
        result_delivery_policy=policy_config.result_delivery_policy or _delivery_policy_for_scan_verdict(verdict),
    )


def policy_decision_from_handoff_decision(handoff: PolicyHandoffDecision) -> PolicyDecision:
    summary_targets = handoff.delivery.workflow_summary_targets or handoff.delivery.targets
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
    verdict = _normalized_verdict(handoff.scan_result.verdict)
    explicit = item_payload.get("policyDecision") or item_payload.get("policy_decision")
    if explicit:
        decision = PolicyDecision.model_validate(explicit)
        return _build_stub_handoff_decision(handoff, decision)

    remediation_by_verdict = policy_config.remediation_plan_by_verdict or {}
    remediation_plan = (
        item_payload.get("remediationPlan")
        or item_payload.get("remediation_plan")
        or remediation_by_verdict.get(verdict)
        or {}
    )
    request_dianna = bool(item_payload.get("requestDianna") or item_payload.get("request_dianna"))
    if not request_dianna:
        auto_dianna = policy_config.auto_dianna_on_verdicts or []
        request_dianna = verdict in auto_dianna
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
    return _build_stub_handoff_decision(handoff, decision)


async def stub_policy_evaluator(request: PolicyEvaluationRequested) -> PolicyDecision:
    handoff = request.as_policy_handoff_request()
    decision = await stub_policy_engine(handoff)
    return policy_decision_from_handoff_decision(decision)
