from __future__ import annotations

import asyncio
from typing import AsyncIterator

import pytest

from dsx_transfer.adapters.sftpgo import SftpGoEventContext, SftpGoTransferPlatformAdapter, sftpgo_context_from_payload
from dsx_transfer.contracts import ScanGate
from dsx_transfer.models import ScanDecision, TransferItem, TransferPlatformContext


async def empty_stream() -> AsyncIterator[bytes]:
    if False:
        yield b""


class RecordingScanGate(ScanGate):
    def __init__(self) -> None:
        self.item: TransferItem | None = None

    async def decide(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> ScanDecision:
        self.item = item
        return ScanDecision(
            verdict="benign",
            action="block",
            file_type="PE32FileType",
            policy_id="block-windows-executables",
            scan_guid="scan-123",
            reason="file_type_rule:PE32FileType",
            details={"scanner": "dsxa"},
        )


def test_transfer_platform_adapter_maps_scan_decision_to_commit_decision() -> None:
    scan_gate = RecordingScanGate()
    adapter = SftpGoTransferPlatformAdapter(scan_gate)

    decision = asyncio.run(
        adapter.decide_commit(
            TransferPlatformContext(
                platform="sftpgo",
                event_type="pre-upload",
                object_identity="uploads/payload.exe",
                source_uri="sftpgo://incoming/uploads/payload.exe",
                user_id="alice",
            ),
            empty_stream(),
        )
    )

    assert decision.action == "block"
    assert decision.verdict == "benign"
    assert decision.file_type == "PE32FileType"
    assert decision.reason == "file_type_rule:PE32FileType"
    assert decision.details["scanner"] == "dsxa"
    assert decision.details["transfer_platform"] == "sftpgo"
    assert decision.details["transfer_platform_event_type"] == "pre-upload"
    assert scan_gate.item is not None
    assert scan_gate.item.object_identity == "uploads/payload.exe"
    assert scan_gate.item.metadata["transfer_platform"] == "sftpgo"


def test_sftpgo_adapter_accepts_sftpgo_event_context() -> None:
    scan_gate = RecordingScanGate()
    adapter = SftpGoTransferPlatformAdapter(scan_gate)

    decision = asyncio.run(
        adapter.decide_sftpgo_event(
            SftpGoEventContext(
                event_type="pre-upload",
                object_identity="incoming/tool.exe",
                user_id="alice",
                session_id="session-1",
                metadata={"protocol": "sftp"},
            ),
            empty_stream(),
        )
    )

    assert decision.action == "block"
    assert decision.details["user_id"] == "alice"
    assert decision.details["session_id"] == "session-1"
    assert scan_gate.item is not None
    assert scan_gate.item.metadata["protocol"] == "sftp"


def test_sftpgo_payload_parser_accepts_common_path_fields() -> None:
    context = sftpgo_context_from_payload(
        {
            "event": "upload",
            "virtual_path": "/inbox/file.txt",
            "username": "alice",
            "connection_id": "conn-1",
            "protocol": "sftp",
        },
        event_type="pre-upload",
    )

    assert context.event_type == "pre-upload"
    assert context.object_identity == "/inbox/file.txt"
    assert context.user_id == "alice"
    assert context.session_id == "conn-1"
    assert context.metadata == {"protocol": "sftp"}


def test_sftpgo_payload_parser_requires_object_identity() -> None:
    with pytest.raises(ValueError, match="object identity"):
        sftpgo_context_from_payload({"event": "upload"})


def test_sftpgo_adapter_rejects_other_platform_context() -> None:
    adapter = SftpGoTransferPlatformAdapter(RecordingScanGate())

    with pytest.raises(ValueError, match="unsupported platform"):
        asyncio.run(
            adapter.decide_commit(
                TransferPlatformContext(
                    platform="moveit",
                    event_type="pre-upload",
                    object_identity="payload.exe",
                ),
                empty_stream(),
            )
        )
