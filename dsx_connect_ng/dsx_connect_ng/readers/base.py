from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from dsx_connect_ng.workers.errors import TerminalWorkerError

if TYPE_CHECKING:
    from dsx_connect_ng.jobs.contracts import ScanItemRequested


@dataclass(frozen=True)
class ReadResult:
    local_path: Path | None = None
    details: dict[str, Any] = field(default_factory=dict)


class TerminalScanError(TerminalWorkerError):
    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_error_payload(self) -> dict:
        payload = {
            "code": self.code,
            "message": self.message,
            "retryable": False,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class Reader(ABC):
    """Worker-side content acquisition capability."""

    @abstractmethod
    async def acquire(self, request: "ScanItemRequested") -> ReadResult:
        raise NotImplementedError
