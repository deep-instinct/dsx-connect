from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Annotated, Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from dsx_transfer.adapters.sftpgo import SftpGoTransferPlatformAdapter, sftpgo_context_from_payload
from dsx_transfer.contracts import AuditSink, ScanGate
from dsx_transfer.dsxa_scan_gate import DsxaStreamScanGate
from dsx_transfer.models import AuditEvent, CommitDecision, TransferPlatformContext
from dsx_transfer.scan_gates import StaticVerdictScanGate


logger = logging.getLogger(__name__)


class SftpGoDecisionRequest(BaseModel):
    event: dict[str, Any] = Field(default_factory=dict)
    content_base64: str | None = None
    content_text: str | None = None


def create_app(
    *,
    scan_gate: ScanGate | None = None,
    audit_sink: AuditSink | None = None,
    sftpgo_storage_root: Path | None = None,
    sftpgo_container_root: str = "/srv/sftpgo/data",
    remove_blocked_uploads: bool = True,
    sftpgo_block_response: str = "reject",
) -> FastAPI:
    app = FastAPI(
        title="DSX-Transfer Decision Service",
        description="Guarded Transfer decision endpoints for transfer platform integrations.",
        version="0.1.0",
    )
    app.state.scan_gate = scan_gate or StaticVerdictScanGate()
    app.state.audit_sink = audit_sink
    app.state.sftpgo_storage_root = sftpgo_storage_root
    app.state.sftpgo_container_root = sftpgo_container_root
    app.state.remove_blocked_uploads = remove_blocked_uploads
    app.state.sftpgo_block_response = sftpgo_block_response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/transfer-decisions/sftpgo/pre-upload", response_model=CommitDecision)
    async def sftpgo_pre_upload(
        request: SftpGoDecisionRequest,
        scan_gate: Annotated[ScanGate, Depends(get_scan_gate)],
    ) -> CommitDecision:
        try:
            context = sftpgo_context_from_payload(request.event, event_type="pre-upload")
            content = _request_content(request)
            adapter = SftpGoTransferPlatformAdapter(scan_gate)
            return await adapter.decide_sftpgo_event(context, _single_chunk_stream(content))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/sftpgo/hooks/pre-upload", response_model=CommitDecision)
    async def sftpgo_pre_upload_hook(
        event: dict[str, Any],
        scan_gate: Annotated[ScanGate, Depends(get_scan_gate)],
        audit_sink: Annotated[AuditSink | None, Depends(get_audit_sink)],
    ) -> CommitDecision:
        if isinstance(scan_gate, DsxaStreamScanGate):
            raise HTTPException(
                status_code=409,
                detail=(
                    "SFTPGo pre-upload hooks do not include file bytes. "
                    "Use the generic decision endpoint with content bytes or add a shared-storage upload hook."
                ),
            )
        try:
            context = sftpgo_context_from_payload(event, event_type="pre-upload")
            adapter = SftpGoTransferPlatformAdapter(scan_gate)
            decision = await adapter.decide_sftpgo_event(context, _single_chunk_stream(b""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _log_sftpgo_decision(context.event_type, context.object_identity, decision)
        await _emit_sftpgo_audit(audit_sink, context.to_transfer_platform_context(), decision)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.model_dump(mode="json"))
        return decision

    @app.post("/api/v1/sftpgo/hooks/upload", response_model=CommitDecision)
    async def sftpgo_upload_hook(
        event: dict[str, Any],
        scan_gate: Annotated[ScanGate, Depends(get_scan_gate)],
        audit_sink: Annotated[AuditSink | None, Depends(get_audit_sink)],
        storage_root: Annotated[Path | None, Depends(get_sftpgo_storage_root)],
        container_root: Annotated[str, Depends(get_sftpgo_container_root)],
        remove_blocked_uploads: Annotated[bool, Depends(should_remove_blocked_uploads)],
        block_response: Annotated[str, Depends(get_sftpgo_block_response)],
    ) -> CommitDecision:
        try:
            uploaded_path = _resolve_sftpgo_uploaded_path(
                event,
                storage_root=storage_root,
                container_root=container_root,
            )
            context = sftpgo_context_from_payload(event, event_type="upload")
            adapter = SftpGoTransferPlatformAdapter(scan_gate)
            decision = await adapter.decide_sftpgo_event(context, _file_chunk_stream(uploaded_path))
        except ValueError as exc:
            logger.warning("SFTPGo upload hook rejected event: %s; event=%r", exc, event)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        _log_sftpgo_decision(context.event_type, context.object_identity, decision)
        await _emit_sftpgo_audit(
            audit_sink,
            context.to_transfer_platform_context(),
            decision,
            bytes_written=uploaded_path.stat().st_size if uploaded_path.exists() else 0,
        )
        if not decision.allowed:
            if remove_blocked_uploads:
                uploaded_path.unlink(missing_ok=True)
            if block_response == "allow_after_remove":
                return decision
            raise HTTPException(status_code=403, detail=decision.model_dump(mode="json"))
        return decision

    app.dependency_overrides[get_scan_gate] = lambda: app.state.scan_gate
    app.dependency_overrides[get_audit_sink] = lambda: app.state.audit_sink
    app.dependency_overrides[get_sftpgo_storage_root] = lambda: app.state.sftpgo_storage_root
    app.dependency_overrides[get_sftpgo_container_root] = lambda: app.state.sftpgo_container_root
    app.dependency_overrides[should_remove_blocked_uploads] = lambda: app.state.remove_blocked_uploads
    app.dependency_overrides[get_sftpgo_block_response] = lambda: app.state.sftpgo_block_response
    return app


def get_scan_gate() -> ScanGate:
    raise RuntimeError("get_scan_gate must be overridden by the app factory")


def get_audit_sink() -> AuditSink | None:
    raise RuntimeError("get_audit_sink must be overridden by the app factory")


def get_sftpgo_storage_root() -> Path | None:
    raise RuntimeError("get_sftpgo_storage_root must be overridden by the app factory")


def get_sftpgo_container_root() -> str:
    raise RuntimeError("get_sftpgo_container_root must be overridden by the app factory")


def should_remove_blocked_uploads() -> bool:
    raise RuntimeError("should_remove_blocked_uploads must be overridden by the app factory")


def get_sftpgo_block_response() -> str:
    raise RuntimeError("get_sftpgo_block_response must be overridden by the app factory")


def _request_content(request: SftpGoDecisionRequest) -> bytes:
    if request.content_base64 is not None:
        try:
            return base64.b64decode(request.content_base64, validate=True)
        except ValueError as exc:
            raise ValueError("content_base64 is not valid base64") from exc
    if request.content_text is not None:
        return request.content_text.encode("utf-8")
    return b""


async def _single_chunk_stream(content: bytes) -> AsyncIterator[bytes]:
    if content:
        yield content


async def _file_chunk_stream(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            yield chunk


def _resolve_sftpgo_uploaded_path(event: dict[str, Any], *, storage_root: Path | None, container_root: str) -> Path:
    if storage_root is None:
        raise ValueError("SFTPGo upload hook requires --sftpgo-storage-root")

    root = storage_root.resolve()
    container_root = container_root.rstrip("/")
    raw_path = _first_string(
        event,
        "fs_path",
        "filesystem_path",
        "local_path",
        "file_path",
        "filepath",
        "path",
    )
    if raw_path:
        if raw_path.startswith(f"{container_root}/"):
            relative_path = raw_path[len(container_root) + 1 :]
            candidate = root / relative_path
        else:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = root / candidate
    else:
        username = _first_string(event, "username", "user")
        object_identity = _first_string(event, "virtual_path", "path", "object_identity", "name")
        if object_identity is None:
            raise ValueError("SFTPGo upload event did not include a file path")
        object_relative_path = object_identity.lstrip("/")
        candidate = root / username / object_relative_path if username else root / object_relative_path

    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"resolved upload path is outside the configured storage root: {resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"uploaded file does not exist or is not a file: {resolved}")
    return resolved


def _log_sftpgo_decision(event_type: str, object_identity: str, decision: CommitDecision) -> None:
    logger.info(
        "SFTPGo %s decision object_identity=%r action=%s verdict=%s reason=%s file_type=%s",
        event_type,
        object_identity,
        decision.action,
        decision.verdict,
        decision.reason,
        decision.file_type,
    )


async def _emit_sftpgo_audit(
    audit_sink: AuditSink | None,
    context: TransferPlatformContext,
    decision: CommitDecision,
    *,
    bytes_written: int = 0,
) -> None:
    if audit_sink is None:
        return
    await audit_sink.emit(
        AuditEvent(
            event_type="transfer_platform_decision",
            transfer_id=context.transfer_id or context.session_id or f"{context.platform}:{context.event_type}",
            source_uri=context.source_uri or f"{context.platform}://event/{context.object_identity}",
            destination_uri=context.destination_uri or f"{context.platform}://commit/{context.object_identity}",
            object_identity=context.object_identity,
            state="allowed" if decision.allowed else "blocked",
            verdict=decision.verdict,
            action=decision.action,
            file_type=decision.file_type,
            policy_id=decision.policy_id,
            bytes_written=bytes_written,
            transfer_platform=context.platform,
            platform_event_type=context.event_type,
            user_id=context.user_id,
            session_id=context.session_id,
            details=decision.details,
        )
    )


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


app = create_app()
