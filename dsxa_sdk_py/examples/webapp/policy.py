from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dsxa_sdk_py.models import ScanResponse, VerdictEnum


@dataclass(frozen=True)
class UploadDecision:
    accepted: bool
    bucket: str
    tone: str
    headline: str


def sanitize_filename(filename: str) -> str:
    candidate = Path(filename or "").name.strip()
    return candidate or "uploaded-file"


EXECUTABLE_FILE_TYPES = {
    "PEFileType",
    "PE32FileType",
    "PE64FileType",
    "ELF32FileType",
    "ELF64FileType",
    "MachoFATFileType",
    "Macho32FileType",
    "Macho64FileType",
}


def _is_executable_file_type(file_type: str | None) -> bool:
    return file_type in EXECUTABLE_FILE_TYPES


def classify_scan(response: ScanResponse, *, block_executables: bool = True) -> UploadDecision:
    file_type = getattr(response.file_info, "file_type", None)
    if block_executables and _is_executable_file_type(file_type):
        return UploadDecision(
            accepted=False,
            bucket="rejected",
            tone="policy",
            headline=f"File type not allowed by policy [{file_type}]",
        )

    verdict = response.verdict
    if verdict == VerdictEnum.BENIGN:
        return UploadDecision(
            accepted=True,
            bucket="accepted",
            tone="accepted",
            headline="Accepted into loan application",
        )
    if verdict == VerdictEnum.MALICIOUS:
        return UploadDecision(
            accepted=False,
            bucket="rejected",
            tone="rejected",
            headline="Blocked as malicious",
        )
    if verdict == VerdictEnum.NON_COMPLIANT:
        return UploadDecision(
            accepted=False,
            bucket="rejected",
            tone="rejected",
            headline="Blocked as non-compliant",
        )
    return UploadDecision(
        accepted=False,
        bucket="review",
        tone="review",
        headline="Not accepted automatically",
    )
