from __future__ import annotations

from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

from dsx_transfer.contracts import ScanGate, TransferPlatformAdapter
from dsx_transfer.models import CommitDecision, TransferItem, TransferPlatformContext


class SftpGoEventContext(BaseModel):
    event_type: str
    object_identity: str
    source_uri: str | None = None
    destination_uri: str | None = None
    transfer_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_transfer_platform_context(self) -> TransferPlatformContext:
        return TransferPlatformContext(
            platform="sftpgo",
            event_type=self.event_type,
            object_identity=self.object_identity,
            source_uri=self.source_uri,
            destination_uri=self.destination_uri,
            transfer_id=self.transfer_id,
            user_id=self.user_id,
            session_id=self.session_id,
            metadata=self.metadata,
        )


class SftpGoTransferPlatformAdapter(TransferPlatformAdapter):
    def __init__(self, scan_gate: ScanGate) -> None:
        self.scan_gate = scan_gate

    async def decide_commit(self, context: TransferPlatformContext, chunks: AsyncIterator[bytes]) -> CommitDecision:
        if context.platform != "sftpgo":
            raise ValueError(f"unsupported platform for SFTPGo adapter: {context.platform}")

        item = TransferItem(
            source_uri=context.source_uri or f"sftpgo://event/{context.object_identity}",
            destination_uri=context.destination_uri or f"sftpgo://commit/{context.object_identity}",
            object_identity=context.object_identity,
            metadata={
                "transfer_platform": context.platform,
                "transfer_platform_event_type": context.event_type,
                "transfer_id": context.transfer_id,
                "user_id": context.user_id,
                "session_id": context.session_id,
                **context.metadata,
            },
        )
        scan_decision = await self.scan_gate.decide(item, chunks)
        return CommitDecision.from_scan_decision(
            scan_decision,
            details={
                "transfer_platform": context.platform,
                "transfer_platform_event_type": context.event_type,
                "transfer_id": context.transfer_id,
                "user_id": context.user_id,
                "session_id": context.session_id,
            },
        )

    async def decide_sftpgo_event(self, event: SftpGoEventContext, chunks: AsyncIterator[bytes]) -> CommitDecision:
        return await self.decide_commit(event.to_transfer_platform_context(), chunks)


def sftpgo_context_from_payload(payload: dict[str, Any], *, event_type: str | None = None) -> SftpGoEventContext:
    object_identity = _first_string(
        payload,
        "object_identity",
        "virtual_path",
        "path",
        "filepath",
        "file_path",
        "name",
    )
    if object_identity is None:
        raise ValueError("SFTPGo payload did not include an object identity field")

    resolved_event_type = event_type or _first_string(payload, "event_type", "event", "action") or "unknown"
    user_id = _first_string(payload, "user_id", "username", "user")
    session_id = _first_string(payload, "session_id", "connection_id")
    transfer_id = _first_string(payload, "transfer_id", "request_id", "id")
    source_uri = _first_string(payload, "source_uri")
    destination_uri = _first_string(payload, "destination_uri")

    return SftpGoEventContext(
        event_type=resolved_event_type,
        object_identity=object_identity,
        source_uri=source_uri,
        destination_uri=destination_uri,
        transfer_id=transfer_id,
        user_id=user_id,
        session_id=session_id,
        metadata={
            key: value
            for key, value in payload.items()
            if key
            not in {
                "object_identity",
                "virtual_path",
                "path",
                "filepath",
                "file_path",
                "name",
                "event_type",
                "event",
                "action",
                "user_id",
                "username",
                "user",
                "session_id",
                "connection_id",
                "transfer_id",
                "request_id",
                "id",
                "source_uri",
                "destination_uri",
            }
        },
    )


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None
