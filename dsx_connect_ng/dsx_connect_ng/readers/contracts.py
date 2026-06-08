from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.jobs.models import ContentSource


ReaderStrategy = Literal["proxy", "native", "cached", "quarantine"]
ConnectorProxyReadMode = Literal["stream", "buffer", "artifact_ref"]
ArtifactRefKind = Literal["signed_url", "local_path", "opaque_locator"]
ReaderErrorCode = Literal[
    "auth_error",
    "permission_error",
    "object_not_found",
    "rate_limit",
    "transient_platform_error",
    "content_unavailable",
    "invalid_read_context",
    "unsupported_response_mode",
]


class ArtifactRef(BaseModel):
    kind: ArtifactRefKind
    locator: str
    expires_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ConnectorProxyReadRequest(BaseModel):
    job_id: str
    job_item_id: str
    integration_id: str
    scope_id: str | None = None
    object_identity: str
    content_source: ContentSource
    read_hint: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    preferred_modes: list[ConnectorProxyReadMode] = Field(default_factory=lambda: ["stream", "artifact_ref", "buffer"])

    @model_validator(mode="after")
    def validate_preferred_modes(self) -> "ConnectorProxyReadRequest":
        if not self.preferred_modes:
            raise ValueError("preferred_modes_must_not_be_empty")
        self.preferred_modes = list(dict.fromkeys(self.preferred_modes))
        return self

    @classmethod
    def from_scan_request(
        cls,
        request: ScanItemRequested,
        *,
        preferred_modes: list[ConnectorProxyReadMode] | None = None,
        options: dict[str, Any] | None = None,
    ) -> "ConnectorProxyReadRequest":
        if not request.integration_id:
            raise ValueError("connector_proxy_reader_requires_integration_id")
        return cls(
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            integration_id=request.integration_id,
            scope_id=request.scope_id,
            object_identity=request.object_identity,
            content_source=request.content_source,
            read_hint=request.read_hint,
            options=options if options is not None else request.scan_options,
            preferred_modes=preferred_modes or ["stream", "artifact_ref", "buffer"],
        )


class ConnectorProxyReadResponse(BaseModel):
    mode: ConnectorProxyReadMode
    content_length: int | None = None
    content_type: str | None = None
    etag: str | None = None
    version: str | None = None
    artifact_ref: ArtifactRef | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_payload(self) -> "ConnectorProxyReadResponse":
        if self.mode == "artifact_ref" and self.artifact_ref is None:
            raise ValueError("artifact_ref_mode_requires_artifact_ref")
        if self.mode != "artifact_ref" and self.artifact_ref is not None:
            raise ValueError("artifact_ref_is_only_valid_for_artifact_ref_mode")
        return self


class ReaderErrorPayload(BaseModel):
    code: ReaderErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)
