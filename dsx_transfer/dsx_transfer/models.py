from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


TransferVerdict = Literal["benign", "malicious", "suspicious", "unknown", "error"]
TransferAction = Literal["allow", "block", "exclude", "quarantine", "manual_review", "error"]
TransferItemState = Literal["planned", "allowed", "blocked", "excluded", "failed", "skipped"]


class TransferItem(BaseModel):
    source_uri: str
    destination_uri: str
    object_identity: str
    size_bytes: int | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransferPlan(BaseModel):
    transfer_id: str
    source_uri: str
    destination_uri: str
    items: list[TransferItem] = Field(default_factory=list)
    policy_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanDecision(BaseModel):
    verdict: TransferVerdict
    action: TransferAction
    file_type: str | None = None
    policy_id: str | None = None
    scan_guid: str | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


class TransferPlatformContext(BaseModel):
    platform: str
    event_type: str
    object_identity: str
    source_uri: str | None = None
    destination_uri: str | None = None
    transfer_id: str | None = None
    user_id: str | None = None
    partner_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommitDecision(BaseModel):
    action: TransferAction
    reason: str | None = None
    policy_id: str | None = None
    scan_guid: str | None = None
    file_type: str | None = None
    verdict: TransferVerdict | None = None
    audit_event_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @classmethod
    def from_scan_decision(
        cls,
        decision: ScanDecision,
        *,
        audit_event_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> "CommitDecision":
        merged_details = dict(decision.details)
        if details:
            merged_details.update(details)
        return cls(
            action=decision.action,
            reason=decision.reason,
            policy_id=decision.policy_id,
            scan_guid=decision.scan_guid,
            file_type=decision.file_type,
            verdict=decision.verdict,
            audit_event_id=audit_event_id,
            details=merged_details,
        )


class ScanObservation(BaseModel):
    verdict: TransferVerdict
    file_type: str | None = None
    scan_guid: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TransferItemOutcome(BaseModel):
    item: TransferItem
    state: TransferItemState
    decision: ScanDecision | None = None
    bytes_written: int = 0
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime = Field(default_factory=utcnow)
    error: dict[str, Any] | None = None


class TransferReport(BaseModel):
    transfer_id: str
    source_uri: str
    destination_uri: str
    policy_id: str | None = None
    outcomes: list[TransferItemOutcome] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime = Field(default_factory=utcnow)

    @computed_field
    @property
    def planned_count(self) -> int:
        return len(self.outcomes)

    @computed_field
    @property
    def allowed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.state == "allowed")

    @computed_field
    @property
    def blocked_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.state == "blocked")

    @computed_field
    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.state == "failed")

    @computed_field
    @property
    def skipped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.state == "skipped")

    @computed_field
    @property
    def excluded_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.state == "excluded")


class CheckpointRecord(BaseModel):
    transfer_id: str
    object_identity: str
    source_uri: str
    destination_uri: str
    state: TransferItemState
    size_bytes: int | None = None
    metadata_fingerprint: str | None = None
    outcome: TransferItemOutcome
    updated_at: datetime = Field(default_factory=utcnow)


class AuditEvent(BaseModel):
    event_type: Literal["transfer_item_outcome", "transfer_platform_decision"] = "transfer_item_outcome"
    transfer_id: str
    source_uri: str
    destination_uri: str
    object_identity: str
    state: TransferItemState
    verdict: TransferVerdict | None = None
    action: TransferAction | None = None
    file_type: str | None = None
    policy_id: str | None = None
    bytes_written: int = 0
    error: dict[str, Any] | None = None
    transfer_platform: str | None = None
    platform_event_type: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    event_time: datetime = Field(default_factory=utcnow)

    @classmethod
    def from_outcome(cls, *, transfer_id: str, outcome: TransferItemOutcome) -> "AuditEvent":
        decision = outcome.decision
        return cls(
            transfer_id=transfer_id,
            source_uri=outcome.item.source_uri,
            destination_uri=outcome.item.destination_uri,
            object_identity=outcome.item.object_identity,
            state=outcome.state,
            verdict=decision.verdict if decision is not None else None,
            action=decision.action if decision is not None else None,
            file_type=decision.file_type if decision is not None else None,
            policy_id=decision.policy_id if decision is not None else None,
            bytes_written=outcome.bytes_written,
            error=outcome.error,
        )
