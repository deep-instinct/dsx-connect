from __future__ import annotations
from enum import StrEnum
from typing import Final
from .namespace import NS


class DeadLetterType(StrEnum):
    SCAN_REQUEST = "scan_request"
    VERDICT_ACTION = "verdict_action"
    SCAN_RESULT = "scan_result"


class DLQKeys:
    @staticmethod
    def key(t: DeadLetterType) -> str:
        return f"{NS}:dlq:{t.value}"

    SCAN_REQUEST: Final[str] = key(DeadLetterType.SCAN_REQUEST)
    VERDICT_ACTION: Final[str] = key(DeadLetterType.VERDICT_ACTION)
    SCAN_RESULT: Final[str] = key(DeadLetterType.SCAN_RESULT)

    @staticmethod
    def all() -> list[str]:
        return [DLQKeys.SCAN_REQUEST, DLQKeys.VERDICT_ACTION, DLQKeys.SCAN_RESULT]