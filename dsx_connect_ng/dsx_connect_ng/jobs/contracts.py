from __future__ import annotations

from datetime import datetime, timezone
import posixpath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from dsx_connect_ng.jobs.models import (
    ConnectorActionRequest,
    ConnectorRemediationRequest,
    ContentSource,
    DeliveryRequest,
    DeliveryRequirements,
    DeliveryResult,
    DiannaResult,
    PolicyDecision,
    PolicyHandoffRequest,
    RemediationRequest,
    RemediationResult,
    ScanResult,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


MessageType = Literal[
    "scan_item_requested",
    "scan_item_completed",
    "scan_item_failed",
    "policy_evaluation_requested",
    "policy_evaluation_completed",
    "policy_evaluation_failed",
    "dianna_analysis_requested",
    "dianna_analysis_completed",
    "dianna_analysis_failed",
    "remediation_requested",
    "remediation_completed",
    "remediation_failed",
    "result_sink_emit_requested",
    "result_sink_emit_completed",
    "result_sink_emit_failed",
    "result_delivery_requested",
    "result_delivery_completed",
    "result_delivery_failed",
]


class MessageEnvelope(BaseModel):
    message_type: MessageType
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    idempotency_key: str | None = None
    emitted_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


class ScanItemRequested(BaseModel):
    message_type: Literal["scan_item_requested"] = "scan_item_requested"
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    idempotency_key: str | None = None
    content_source: ContentSource = Field(default_factory=ContentSource)
    read_hint: dict[str, Any] = Field(default_factory=dict)
    scan_options: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)

    def as_envelope(self) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=self.message_type,
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            idempotency_key=self.idempotency_key,
            emitted_at=self.emitted_at,
            payload={
                "content_source": self.content_source.model_dump(mode="json"),
                "read_hint": self.read_hint,
                "scan_options": self.scan_options,
            },
        )

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "ScanItemRequested":
        return cls(
            job_id=envelope.job_id,
            job_item_id=envelope.job_item_id,
            integration_id=envelope.integration_id,
            scope_id=envelope.scope_id,
            object_identity=envelope.object_identity,
            idempotency_key=envelope.idempotency_key,
            emitted_at=envelope.emitted_at,
            content_source=ContentSource.model_validate(envelope.payload.get("content_source") or {}),
            read_hint=envelope.payload.get("read_hint") or {},
            scan_options=envelope.payload.get("scan_options") or {},
        )


class ScanItemCompleted(BaseModel):
    message_type: Literal["scan_item_completed"] = "scan_item_completed"
    job_id: str
    job_item_id: str
    object_identity: str
    scan_result: ScanResult
    emitted_at: datetime = Field(default_factory=utcnow)


class ScanItemFailed(BaseModel):
    message_type: Literal["scan_item_failed"] = "scan_item_failed"
    job_id: str
    job_item_id: str
    object_identity: str
    error: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


class PolicyEvaluationRequested(BaseModel):
    message_type: Literal["policy_evaluation_requested"] = "policy_evaluation_requested"
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    idempotency_key: str | None = None
    scan_result: ScanResult
    item_payload: dict[str, Any] = Field(default_factory=dict)
    policy_context: dict[str, Any] = Field(default_factory=dict)
    item_metadata: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)

    def as_envelope(self) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=self.message_type,
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            idempotency_key=self.idempotency_key,
            emitted_at=self.emitted_at,
            payload={
                "scan_result": self.scan_result.model_dump(mode="json", by_alias=True),
                "item_payload": self.item_payload,
                "policy_context": self.policy_context,
                "item_metadata": self.item_metadata,
            },
        )

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "PolicyEvaluationRequested":
        return cls(
            job_id=envelope.job_id,
            job_item_id=envelope.job_item_id,
            integration_id=envelope.integration_id,
            scope_id=envelope.scope_id,
            object_identity=envelope.object_identity,
            idempotency_key=envelope.idempotency_key,
            emitted_at=envelope.emitted_at,
            scan_result=ScanResult.model_validate(envelope.payload.get("scan_result") or {}),
            item_payload=envelope.payload.get("item_payload") or {},
            policy_context=envelope.payload.get("policy_context") or {},
            item_metadata=envelope.payload.get("item_metadata") or {},
        )

    def as_policy_handoff_request(self) -> PolicyHandoffRequest:
        return PolicyHandoffRequest(
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            content_source=ContentSource.model_validate(self.item_payload.get("content_source") or {}),
            delivery_requirements=DeliveryRequirements.model_validate(
                self.item_payload.get("delivery_requirements") or {}
            ),
            scan_result=self.scan_result,
            item_payload=self.item_payload,
            policy_context=self.policy_context,
            item_metadata=self.item_metadata,
        )


class PolicyEvaluationCompleted(BaseModel):
    message_type: Literal["policy_evaluation_completed"] = "policy_evaluation_completed"
    job_id: str
    job_item_id: str
    object_identity: str
    policy_result: PolicyDecision
    emitted_at: datetime = Field(default_factory=utcnow)


class PolicyEvaluationFailed(BaseModel):
    message_type: Literal["policy_evaluation_failed"] = "policy_evaluation_failed"
    job_id: str
    job_item_id: str
    object_identity: str
    error: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


class DiannaAnalysisRequested(BaseModel):
    message_type: Literal["dianna_analysis_requested"] = "dianna_analysis_requested"
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    idempotency_key: str | None = None
    content_source: ContentSource = Field(default_factory=ContentSource)
    request_reason: str = "manual"
    scan_result: ScanResult
    request_options: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)

    def as_envelope(self) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=self.message_type,
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            idempotency_key=self.idempotency_key,
            emitted_at=self.emitted_at,
            payload={
                "content_source": self.content_source.model_dump(mode="json"),
                "request_reason": self.request_reason,
                "scan_result": self.scan_result.model_dump(mode="json", by_alias=True),
                "request_options": self.request_options,
            },
        )

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "DiannaAnalysisRequested":
        return cls(
            job_id=envelope.job_id,
            job_item_id=envelope.job_item_id,
            integration_id=envelope.integration_id,
            scope_id=envelope.scope_id,
            object_identity=envelope.object_identity,
            idempotency_key=envelope.idempotency_key,
            emitted_at=envelope.emitted_at,
            content_source=ContentSource.model_validate(envelope.payload.get("content_source") or {}),
            request_reason=envelope.payload.get("request_reason") or "manual",
            scan_result=ScanResult.model_validate(envelope.payload.get("scan_result") or {}),
            request_options=envelope.payload.get("request_options") or {},
        )


class DiannaAnalysisCompleted(BaseModel):
    message_type: Literal["dianna_analysis_completed"] = "dianna_analysis_completed"
    job_id: str
    job_item_id: str
    object_identity: str
    analysis_result: DiannaResult
    emitted_at: datetime = Field(default_factory=utcnow)


class DiannaAnalysisFailed(BaseModel):
    message_type: Literal["dianna_analysis_failed"] = "dianna_analysis_failed"
    job_id: str
    job_item_id: str
    object_identity: str
    error: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


class RemediationRequested(BaseModel):
    message_type: Literal["remediation_requested"] = "remediation_requested"
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    content_source: ContentSource = Field(default_factory=ContentSource)
    scan_result: ScanResult
    remediation_plan: RemediationRequest
    emitted_at: datetime = Field(default_factory=utcnow)

    @field_validator("remediation_plan", mode="before")
    @classmethod
    def coerce_remediation_plan(cls, value: Any) -> Any:
        if isinstance(value, dict) and "remediation_plan" not in value:
            return {"remediation_plan": value}
        return value

    def as_envelope(self) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=self.message_type,
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            emitted_at=self.emitted_at,
            payload={
                "content_source": self.content_source.model_dump(mode="json"),
                "scan_result": self.scan_result.model_dump(mode="json", by_alias=True),
                "remediation_plan": self.remediation_plan.remediation_plan,
            },
        )

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "RemediationRequested":
        return cls(
            job_id=envelope.job_id,
            job_item_id=envelope.job_item_id,
            integration_id=envelope.integration_id,
            scope_id=envelope.scope_id,
            object_identity=envelope.object_identity,
            emitted_at=envelope.emitted_at,
            content_source=ContentSource.model_validate(envelope.payload.get("content_source") or {}),
            scan_result=ScanResult.model_validate(envelope.payload.get("scan_result") or {}),
            remediation_plan=RemediationRequest.model_validate({"remediation_plan": envelope.payload.get("remediation_plan") or {}}),
        )

    def as_connector_action_request(self) -> ConnectorActionRequest:
        return self.as_connector_remediation_request().as_legacy_action_request()

    def as_connector_remediation_request(self) -> ConnectorRemediationRequest:
        plan = self.remediation_plan.remediation_plan
        action = str(plan.get("action") or "nothing").strip().lower()
        if action == "delete":
            return ConnectorRemediationRequest(action="delete")
        if action == "tag_only":
            return ConnectorRemediationRequest(
                action="tag",
                tags={k: str(v) for k, v in (plan.get("tags") or {"Verdict": "Malicious"}).items()},
            )
        if action == "quarantine":
            quarantine_target = plan.get("quarantineTarget") or {}
            move_target = (
                plan.get("targetPath")
                or plan.get("target_path")
                or (quarantine_target.get("path"))
                or (quarantine_target.get("prefix"))
            )
            tag_enabled = bool(plan.get("tag"))
            resolved_filename = _resolved_quarantine_filename(
                self.content_source.locator or self.object_identity,
                self.job_item_id,
                suffix_length=int(quarantine_target.get("suffix_length") or 10),
            )
            destination: dict[str, Any] = {}
            if move_target:
                destination["path"] = str(move_target)
            destination["filename"] = resolved_filename
            return ConnectorRemediationRequest(
                action="movetag" if tag_enabled else "move",
                destination=destination,
                tags={k: str(v) for k, v in (plan.get("tags") or {"Verdict": "Malicious"}).items()} if tag_enabled else {},
                details={
                    "quarantine_target": quarantine_target,
                    "resolved_filename": resolved_filename,
                },
            )
        return ConnectorRemediationRequest(action="nothing")


def _quarantine_suffix_token(job_item_id: str, *, suffix_length: int) -> str:
    normalized = str(job_item_id).strip()
    if normalized.startswith("job_item_"):
        normalized = normalized[len("job_item_"):]
    token = "".join(ch for ch in normalized if ch.isalnum()).lower()
    if token:
        return token[: max(1, suffix_length)]
    return normalized[: max(1, suffix_length)] or "quarantine"


def _resolved_quarantine_filename(source_locator: str, job_item_id: str, *, suffix_length: int) -> str:
    base_name = posixpath.basename(str(source_locator).rstrip("/")) or "quarantine-object"
    suffix = _quarantine_suffix_token(job_item_id, suffix_length=suffix_length)
    return f"{base_name}_{suffix}"


class RemediationCompleted(BaseModel):
    message_type: Literal["remediation_completed"] = "remediation_completed"
    job_id: str
    job_item_id: str
    object_identity: str
    remediation_result: RemediationResult
    emitted_at: datetime = Field(default_factory=utcnow)


class RemediationFailed(BaseModel):
    message_type: Literal["remediation_failed"] = "remediation_failed"
    job_id: str
    job_item_id: str
    object_identity: str
    error: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


class ResultSinkEmitRequested(BaseModel):
    message_type: Literal["result_sink_emit_requested", "result_delivery_requested"] = "result_sink_emit_requested"
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    result_type: Literal["scan_result", "remediation_result", "dianna_result", "workflow_summary"] = "workflow_summary"
    result_payload: dict[str, Any] = Field(default_factory=dict)
    final_result: dict[str, Any] = Field(default_factory=dict)
    delivery_target: DeliveryRequest
    emitted_at: datetime = Field(default_factory=utcnow)

    @field_validator("delivery_target", mode="before")
    @classmethod
    def coerce_delivery_target(cls, value: Any) -> Any:
        if isinstance(value, dict) and "delivery_target" not in value:
            return {"delivery_target": value}
        return value

    def as_envelope(self) -> MessageEnvelope:
        return MessageEnvelope(
            message_type=self.message_type,
            job_id=self.job_id,
            job_item_id=self.job_item_id,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=self.object_identity,
            emitted_at=self.emitted_at,
            payload={
                "result_type": self.result_type,
                "result_payload": self.result_payload,
                "final_result": self.final_result,
                "delivery_target": self.delivery_target.delivery_target,
            },
        )

    @classmethod
    def from_envelope(cls, envelope: MessageEnvelope) -> "ResultSinkEmitRequested":
        return cls(
            job_id=envelope.job_id,
            job_item_id=envelope.job_item_id,
            integration_id=envelope.integration_id,
            scope_id=envelope.scope_id,
            object_identity=envelope.object_identity,
            emitted_at=envelope.emitted_at,
            result_type=envelope.payload.get("result_type") or "workflow_summary",
            result_payload=envelope.payload.get("result_payload") or {},
            final_result=envelope.payload.get("final_result") or {},
            delivery_target=DeliveryRequest.model_validate({"delivery_target": envelope.payload.get("delivery_target") or {}}),
        )


class ResultSinkEmitCompleted(BaseModel):
    message_type: Literal["result_sink_emit_completed", "result_delivery_completed"] = "result_sink_emit_completed"
    job_id: str
    job_item_id: str
    object_identity: str
    delivery_result: DeliveryResult
    emitted_at: datetime = Field(default_factory=utcnow)


class ResultSinkEmitFailed(BaseModel):
    message_type: Literal["result_sink_emit_failed", "result_delivery_failed"] = "result_sink_emit_failed"
    job_id: str
    job_item_id: str
    object_identity: str
    error: dict[str, Any] = Field(default_factory=dict)
    emitted_at: datetime = Field(default_factory=utcnow)


# Legacy aliases kept during the result-sink rename.
ResultDeliveryRequested = ResultSinkEmitRequested
ResultDeliveryCompleted = ResultSinkEmitCompleted
ResultDeliveryFailed = ResultSinkEmitFailed
