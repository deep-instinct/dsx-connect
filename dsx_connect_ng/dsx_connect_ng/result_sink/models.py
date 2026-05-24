from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from dsx_connect_ng.jobs.contracts import ResultSinkEmitRequested


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


ResultEventType = Literal["scan_result", "remediation_result", "dianna_result", "workflow_summary"]


class ResultSinkEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    event_type: ResultEventType
    event_time: datetime = Field(default_factory=utcnow)
    job_id: str
    job_item_id: str
    integration_id: str | None = None
    scope_id: str | None = None
    object_identity: str
    file_hash: str | None = None
    scan_guid: str | None = None
    verdict: str | None = None
    file_type: str | None = None
    content_source_mode: str | None = None
    scanner_metadata: dict[str, Any] | None = None
    delivery_target: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    workflow_summary: dict[str, Any] | None = None

    @classmethod
    def from_result_sink_emit_request(cls, request: ResultSinkEmitRequested) -> "ResultSinkEvent":
        payload = request.result_payload or {}
        final_result = request.final_result or {}
        scan_payload = final_result.get("scan") or {}
        scan_metadata = final_result.get("scanMetadata") or {}
        file_info = scan_payload.get("file_info") or {}
        content_source = final_result.get("contentSource") or {}
        return cls(
            event_type=request.result_type,
            event_time=request.emitted_at,
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            integration_id=request.integration_id,
            scope_id=request.scope_id,
            object_identity=request.object_identity,
            file_hash=file_info.get("file_hash"),
            scan_guid=scan_payload.get("scan_guid"),
            verdict=scan_payload.get("verdict"),
            file_type=file_info.get("file_type"),
            content_source_mode=content_source.get("mode"),
            scanner_metadata=scan_metadata,
            delivery_target=request.delivery_target.delivery_target,
            payload=payload,
            workflow_summary=final_result if request.result_type == "workflow_summary" else None,
        )

    @classmethod
    def from_result_delivery_request(cls, request: ResultSinkEmitRequested) -> "ResultSinkEvent":
        return cls.from_result_sink_emit_request(request)
