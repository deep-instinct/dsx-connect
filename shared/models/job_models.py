from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DomainJobType(str, Enum):
    MONITOR_EVENT_INGEST = "MonitorEventIngestJob"
    FULL_SCAN_SCOPE = "FullScanScopeJob"
    ENUMERATE_SCOPE_PAGE = "EnumerateScopePageJob"
    SCAN_OBJECT = "ScanObjectJob"
    FINALIZE_SCAN_OBJECT = "FinalizeScanObjectJob"
    APPLY_REMEDIATION = "ApplyRemediationJob"
    SEND_NOTIFICATION = "SendNotificationJob"
    SCHEDULE_RETRY = "ScheduleRetryJob"


class DomainJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELED = "canceled"


class ScanSourceType(str, Enum):
    MONITORING = "monitoring"
    FULL_SCAN = "full_scan"
    MANUAL = "manual"


class ScanOutcome(str, Enum):
    CLEAN = "clean"
    MALICIOUS = "malicious"
    UNABLE_TO_SCAN = "unable_to_scan"
    FETCH_FAILED = "fetch_failed"
    TIMEOUT = "timeout"
    UNSUPPORTED_TYPE = "unsupported_type"
    POLICY_BLOCKED = "policy_blocked"


class JobEnvelope(BaseModel):
    """
    Canonical domain-job envelope for broker transport and durable ledgering.
    """

    schema_version: Literal["v1"] = "v1"
    job_id: str = Field(min_length=1)
    job_type: DomainJobType
    state: DomainJobState = DomainJobState.QUEUED

    integration_id: str = Field(min_length=1)
    scope_id: str | None = None
    object_identity: str | None = None

    parent_job_id: str | None = None
    root_job_id: str | None = None
    correlation_id: str | None = None

    source_type: ScanSourceType | None = None
    source_entity_id: str | None = None

    idempotency_key: str = Field(min_length=1)
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1)

    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    scheduled_at: str | None = None

    outcome: ScanOutcome | None = None
    outcome_reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

