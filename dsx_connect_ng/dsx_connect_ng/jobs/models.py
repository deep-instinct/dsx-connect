from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobSubmitRequest(BaseModel):
    job_id: str | None = None
    job_type: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchJobItemInput(BaseModel):
    object_identity: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchJobSubmitRequest(BaseModel):
    job_id: str | None = None
    job_type: str = "scan.batch"
    integration_id: str | None = None
    scope_id: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    items: list[BatchJobItemInput] = Field(default_factory=list)


class DiannaAnalysisRequest(BaseModel):
    reason: Literal["manual", "auto_on_malicious"] = "manual"
    wait_for_delivery: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


ContentSourceMode = Literal["original", "quarantine", "cached", "none"]


class ContentSource(BaseModel):
    mode: ContentSourceMode = "original"
    locator: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    available_until: datetime | None = None


class DeliveryRequirements(BaseModel):
    wait_for_dianna: bool = False


class DeliveryRequest(BaseModel):
    delivery_target: dict[str, Any] = Field(default_factory=dict)


class RemediationRequest(BaseModel):
    remediation_plan: dict[str, Any] = Field(default_factory=dict)


StageResultDeliveryMode = Literal[
    "never",
    "all_results",
    "malicious_only",
    "failures_only",
    "completed_only",
    "all_outcomes",
]

AdmissionAction = Literal["accept_and_dispatch", "accept_and_hold", "reject"]
DispatchGateAction = Literal["dispatch", "hold"]
HealthScope = Literal["global", "integration"]


class StageResultDeliveryPolicy(BaseModel):
    scan: StageResultDeliveryMode = "never"
    remediation: StageResultDeliveryMode = "never"
    dianna: StageResultDeliveryMode = "never"


class PolicyStageResult(BaseModel):
    policy_id: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)


class StageApplicabilityDecision(BaseModel):
    state: Literal["pending", "skipped", "requested"] = "pending"
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeliveryDispatchDecision(BaseModel):
    request_now: bool = False
    wait_for_dianna: bool = False
    targets: list[dict[str, Any]] = Field(default_factory=list)
    scan_targets: list[dict[str, Any]] = Field(default_factory=list)
    remediation_targets: list[dict[str, Any]] = Field(default_factory=list)
    dianna_targets: list[dict[str, Any]] = Field(default_factory=list)
    workflow_summary_targets: list[dict[str, Any]] = Field(default_factory=list)


class HealthSignal(BaseModel):
    signal_type: str
    subsystem: Literal["scan_dispatch", "scanner", "reader", "connector_proxy"]
    scope: HealthScope = "global"
    scope_id: str | None = None
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class ScanDispatchGateDecision(BaseModel):
    subsystem: Literal["scan_dispatch"] = "scan_dispatch"
    scope: HealthScope = "global"
    scope_id: str | None = None
    admission_action: AdmissionAction = "accept_and_dispatch"
    dispatch_action: DispatchGateAction = "dispatch"
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutionAdmissionStatus(BaseModel):
    default_action: AdmissionAction = "accept_and_dispatch"
    scan_dispatch: list[ScanDispatchGateDecision] = Field(default_factory=list)
    active_signals: list[HealthSignal] = Field(default_factory=list)


class ContentPreservationDecision(BaseModel):
    mode: ContentSourceMode = "none"
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    remediation_plan: dict[str, Any] = Field(default_factory=dict)
    delivery_target: dict[str, Any] = Field(default_factory=dict)
    request_dianna: bool = False
    wait_for_dianna_before_delivery: bool = False
    dianna_reason: Literal["manual", "auto_on_malicious"] = "auto_on_malicious"
    dianna_options: dict[str, Any] = Field(default_factory=dict)


class PolicyHandoffRequest(BaseModel):
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    content_source: ContentSource = Field(default_factory=ContentSource)
    delivery_requirements: DeliveryRequirements = Field(default_factory=DeliveryRequirements)
    scan_result: "ScanResult"
    item_payload: dict[str, Any] = Field(default_factory=dict)
    policy_context: dict[str, Any] = Field(default_factory=dict)
    item_metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyHandoffDecision(BaseModel):
    policy_stage_result: PolicyStageResult = Field(default_factory=PolicyStageResult)
    remediation: StageApplicabilityDecision = Field(default_factory=StageApplicabilityDecision)
    dianna: StageApplicabilityDecision = Field(default_factory=StageApplicabilityDecision)
    delivery: DeliveryDispatchDecision = Field(default_factory=DeliveryDispatchDecision)
    content_preservation: ContentPreservationDecision = Field(default_factory=ContentPreservationDecision)
    result_delivery_policy: StageResultDeliveryPolicy = Field(default_factory=StageResultDeliveryPolicy)


class ScanResult(BaseModel):
    verdict: str
    scan_guid: str | None = None
    verdict_details: dict[str, Any] = Field(default_factory=dict)
    file_info: dict[str, Any] | None = None
    protected_entity: int | None = None
    scan_duration_in_microseconds: int | None = None
    container_files_scanned: int | None = None
    container_files_scanned_size: int | None = None
    x_custom_metadata: str | None = Field(default=None, alias="X-Custom-Metadata")
    last_update_time: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_scan_result(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "scan_guid" in value or "verdict_details" in value or "file_info" in value:
            return value
        details = value.get("details") or {}
        file_info = details.get("fileInfo")
        verdict_details = details.get("verdictDetails") or {}
        scanner_metadata = value.get("scannerMetadata") or {}
        normalized = dict(value)
        normalized["scan_guid"] = normalized.pop("scanGuid", normalized.get("scan_guid"))
        normalized["file_info"] = file_info or (
            {"file_type": value.get("fileType")} if value.get("fileType") is not None else None
        )
        normalized["verdict_details"] = verdict_details
        normalized["protected_entity"] = scanner_metadata.get("protectedEntity")
        normalized["scan_duration_in_microseconds"] = normalized.pop(
            "scanDurationUs",
            normalized.get("scan_duration_in_microseconds"),
        )
        normalized["container_files_scanned"] = details.get("containerFilesScanned")
        normalized["container_files_scanned_size"] = details.get("containerFilesScannedSize")
        normalized["X-Custom-Metadata"] = details.get("xCustomMetadata")
        normalized["last_update_time"] = details.get("lastUpdateTime")
        return normalized

    @property
    def file_type(self) -> str | None:
        return (self.file_info or {}).get("file_type")

    @property
    def scan_duration_us(self) -> int | None:
        return self.scan_duration_in_microseconds

    @property
    def details(self) -> dict[str, Any]:
        return {
            "verdictDetails": self.verdict_details,
            "fileInfo": self.file_info,
            "containerFilesScanned": self.container_files_scanned,
            "containerFilesScannedSize": self.container_files_scanned_size,
            "xCustomMetadata": self.x_custom_metadata,
            "lastUpdateTime": self.last_update_time,
        }


class RemediationResult(BaseModel):
    action: str
    outcome: str
    target_path: str | None = Field(default=None, alias="targetPath")
    details: dict[str, Any] = Field(default_factory=dict)


class DiannaResult(BaseModel):
    analysis_id: str | None = Field(default=None, alias="analysisId")
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class DeliveryResult(BaseModel):
    destination: str | None = None
    outcome: str
    external_reference: str | None = Field(default=None, alias="externalReference")
    details: dict[str, Any] = Field(default_factory=dict)


class DomainJobEnvelope(BaseModel):
    job_id: str
    job_type: str
    state: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str | None = None
    idempotency_key: str | None = None
    job_item_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class JobRecord(BaseModel):
    job_id: str
    job_type: str
    state: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None

    def as_envelope(
        self,
        *,
        state_override: str | None = None,
        job_item_id: str | None = None,
        object_identity: str | None = None,
        payload_override: dict[str, Any] | None = None,
    ) -> DomainJobEnvelope:
        return DomainJobEnvelope(
            job_id=self.job_id,
            job_type=self.job_type,
            state=state_override or self.state,
            integration_id=self.integration_id,
            scope_id=self.scope_id,
            object_identity=object_identity or self.object_identity,
            idempotency_key=self.idempotency_key,
            job_item_id=job_item_id,
            payload=payload_override if payload_override is not None else self.payload,
            created_at=self.created_at,
        )


class JobCreate(BaseModel):
    job_id: str | None = None
    job_type: str
    state: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


StageState = Literal["pending", "running", "completed", "failed", "skipped"]
JobItemState = Literal[
    "accepted",
    "publish_pending",
    "queued",
    "scanning",
    "scanned",
    "remediating",
    "deliver_pending",
    "delivering_result",
    "completed",
    "failed",
    "cancelled",
]


class StageRecord(BaseModel):
    state: StageState = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class JobItemRecord(BaseModel):
    job_item_id: str
    job_id: str
    item_index: int
    object_identity: str
    state: JobItemState
    payload: dict[str, Any] = Field(default_factory=dict)
    content_source: ContentSource = Field(default_factory=ContentSource)
    delivery_requirements: DeliveryRequirements = Field(default_factory=DeliveryRequirements)
    error: dict[str, Any] | None = None
    scan_stage: StageRecord = Field(default_factory=StageRecord)
    policy_stage: StageRecord = Field(default_factory=StageRecord)
    remediation_stage: StageRecord = Field(default_factory=StageRecord)
    delivery_stage: StageRecord = Field(default_factory=StageRecord)
    dianna_stage: StageRecord = Field(default_factory=StageRecord)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class JobItemCreate(BaseModel):
    job_item_id: str | None = None
    job_id: str
    item_index: int
    object_identity: str
    state: JobItemState
    payload: dict[str, Any] = Field(default_factory=dict)
    content_source: ContentSource = Field(default_factory=ContentSource)
    delivery_requirements: DeliveryRequirements = Field(default_factory=DeliveryRequirements)
    error: dict[str, Any] | None = None
    scan_stage: StageRecord = Field(default_factory=StageRecord)
    policy_stage: StageRecord = Field(default_factory=StageRecord)
    remediation_stage: StageRecord = Field(default_factory=StageRecord)
    delivery_stage: StageRecord = Field(default_factory=StageRecord)
    dianna_stage: StageRecord = Field(default_factory=StageRecord)


class StageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class ScanStageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    scan_result: ScanResult | None = None
    scanner_metadata: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "ScanStageUpdateRequest":
        if self.state == "completed" and self.scan_result is None:
            raise ValueError("completed_scan_stage_requires_scan_result")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed_scan_stage_requires_error")
        return self

    def as_stage_update_request(self) -> StageUpdateRequest:
        return StageUpdateRequest(
            state=self.state,
            result=self.scan_result.model_dump(mode="json", by_alias=True) if self.scan_result is not None else None,
            metadata=self.scanner_metadata,
            error=self.error,
        )


class RemediationStageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    remediation_result: RemediationResult | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "RemediationStageUpdateRequest":
        if self.state == "completed" and self.remediation_result is None:
            raise ValueError("completed_remediation_stage_requires_result")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed_remediation_stage_requires_error")
        return self

    def as_stage_update_request(self) -> StageUpdateRequest:
        return StageUpdateRequest(
            state=self.state,
            result=self.remediation_result.model_dump(mode="json", by_alias=True) if self.remediation_result is not None else None,
            error=self.error,
        )


class PolicyStageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    decision: PolicyDecision | PolicyHandoffDecision | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "PolicyStageUpdateRequest":
        if self.state == "completed" and self.decision is None:
            raise ValueError("completed_policy_stage_requires_decision")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed_policy_stage_requires_error")
        return self

    def as_stage_update_request(self) -> StageUpdateRequest:
        return StageUpdateRequest(
            state=self.state,
            result=self.decision.model_dump(mode="json") if self.decision is not None else None,
            error=self.error,
        )


class DiannaStageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    dianna_result: DiannaResult | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "DiannaStageUpdateRequest":
        if self.state == "completed" and self.dianna_result is None:
            raise ValueError("completed_dianna_stage_requires_result")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed_dianna_stage_requires_error")
        return self

    def as_stage_update_request(self) -> StageUpdateRequest:
        return StageUpdateRequest(
            state=self.state,
            result=self.dianna_result.model_dump(mode="json", by_alias=True) if self.dianna_result is not None else None,
            error=self.error,
        )


class DeliveryStageUpdateRequest(BaseModel):
    state: Literal["running", "completed", "failed", "skipped"]
    delivery_result: DeliveryResult | None = None
    error: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> "DeliveryStageUpdateRequest":
        if self.state == "completed" and self.delivery_result is None:
            raise ValueError("completed_delivery_stage_requires_result")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed_delivery_stage_requires_error")
        return self

    def as_stage_update_request(self) -> StageUpdateRequest:
        return StageUpdateRequest(
            state=self.state,
            result=self.delivery_result.model_dump(mode="json", by_alias=True) if self.delivery_result is not None else None,
            error=self.error,
        )


class JobItemSummary(BaseModel):
    total: int = 0
    accepted: int = 0
    publish_pending: int = 0
    queued: int = 0
    scanning: int = 0
    scanned: int = 0
    remediating: int = 0
    deliver_pending: int = 0
    delivering_result: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class BatchJobRecord(BaseModel):
    job: JobRecord
    item_summary: JobItemSummary


class OutboxRecord(BaseModel):
    outbox_id: str
    job_id: str
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    publish_state: str
    publish_attempts: int = 0
    last_error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    published_at: datetime | None = None


class OutboxFlushResult(BaseModel):
    attempted: int = 0
    published: int = 0
    failed: int = 0
    records: list[OutboxRecord] = Field(default_factory=list)
