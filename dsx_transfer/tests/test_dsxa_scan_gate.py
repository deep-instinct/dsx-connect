from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from dsx_transfer.dsxa_scan_gate import DsxaStreamScanGate, scan_observation_from_dsxa_response
from dsx_transfer.models import TransferItem
from dsx_transfer.policy import GuardedTransferPolicy


@dataclass
class FakeFileInfo:
    file_type: str | None = None


@dataclass
class FakeDsxaResponse:
    verdict: str
    scan_guid: str = "scan-1"
    file_info: FakeFileInfo | None = None

    def model_dump(self, **_kwargs):
        return {
            "verdict": self.verdict,
            "scan_guid": self.scan_guid,
            "file_info": {"file_type": self.file_info.file_type if self.file_info else None},
        }


class FakeDsxaClient:
    def __init__(self, response: FakeDsxaResponse) -> None:
        self.response = response
        self.bytes_seen = 0

    async def scan_binary_stream(self, data: AsyncIterator[bytes], **_kwargs):
        async for chunk in data:
            self.bytes_seen += len(chunk)
        return self.response


async def chunks() -> AsyncIterator[bytes]:
    yield b"abc"
    yield b"def"


def item() -> TransferItem:
    return TransferItem(
        source_uri="file:///source/payload.bin",
        destination_uri="file:///dest/payload.bin",
        object_identity="payload.bin",
    )


def test_scan_observation_normalizes_dsxa_response() -> None:
    observation = scan_observation_from_dsxa_response(
        FakeDsxaResponse(verdict="Benign", scan_guid="scan-123", file_info=FakeFileInfo("PE32FileType"))
    )

    assert observation.verdict == "benign"
    assert observation.scan_guid == "scan-123"
    assert observation.file_type == "PE32FileType"


def test_dsxa_stream_scan_gate_evaluates_policy() -> None:
    client = FakeDsxaClient(
        FakeDsxaResponse(verdict="Benign", file_info=FakeFileInfo("PE32FileType"))
    )
    gate = DsxaStreamScanGate(
        client,
        policy=GuardedTransferPolicy(
            policy_id="policy-dsxa",
            file_type_actions={"windows_executables": "block"},
        ),
    )

    decision = asyncio.run(gate.decide(item(), chunks()))

    assert client.bytes_seen == 6
    assert decision.verdict == "benign"
    assert decision.file_type == "PE32FileType"
    assert decision.action == "block"
    assert decision.reason == "file_type_rule:PE32FileType"
