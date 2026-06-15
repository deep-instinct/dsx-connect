from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from dsx_transfer.models import (
    AuditEvent,
    CheckpointRecord,
    CommitDecision,
    ScanDecision,
    TransferItem,
    TransferItemOutcome,
    TransferPlatformContext,
    TransferPlan,
)
from shared.object_storage import ObjectDiscoverer, ObjectInfo, ObjectReader, ObjectRef, ObjectScope, ObjectWriter


class SourceAdapter(ABC):
    @abstractmethod
    async def plan(self, *, destination_uri: str, transfer_id: str, policy_id: str | None = None) -> TransferPlan:
        raise NotImplementedError

    @abstractmethod
    async def open_item(self, item: TransferItem) -> AsyncIterator[bytes]:
        raise NotImplementedError


class SinkAdapter(ABC):
    @abstractmethod
    async def write_item(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> int:
        raise NotImplementedError


class ScanGate(ABC):
    @abstractmethod
    async def decide(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> ScanDecision:
        raise NotImplementedError


class TransferPlatformAdapter(ABC):
    @abstractmethod
    async def decide_commit(self, context: TransferPlatformContext, chunks: AsyncIterator[bytes]) -> CommitDecision:
        raise NotImplementedError


class AuditSink(ABC):
    @abstractmethod
    async def emit(self, event: AuditEvent) -> None:
        raise NotImplementedError


class CheckpointStore(ABC):
    @abstractmethod
    async def get(self, *, transfer_id: str, item: TransferItem) -> CheckpointRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def put(self, *, transfer_id: str, outcome: TransferItemOutcome) -> None:
        raise NotImplementedError
