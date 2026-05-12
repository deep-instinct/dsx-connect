from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dsxa_sdk_py.models import VerdictEnum


@dataclass(frozen=True)
class UploadDecision:
    accepted: bool
    bucket: str
    headline: str


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename or "").name.strip()
    return candidate or "uploaded-file"


def classify_verdict(verdict: VerdictEnum) -> UploadDecision:
    if verdict == VerdictEnum.BENIGN:
        return UploadDecision(
            accepted=True,
            bucket="accepted",
            headline="Accepted into loan application",
        )
    if verdict == VerdictEnum.MALICIOUS:
        return UploadDecision(
            accepted=False,
            bucket="rejected",
            headline="Blocked as malicious",
        )
    if verdict == VerdictEnum.NON_COMPLIANT:
        return UploadDecision(
            accepted=False,
            bucket="rejected",
            headline="Blocked as non-compliant",
        )
    return UploadDecision(
        accepted=False,
        bucket="review",
        headline="Not accepted automatically",
    )
