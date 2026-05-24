from __future__ import annotations

from pathlib import Path

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.base import ReadResult, Reader, TerminalScanError


def coalesce_path_candidates(request: ScanItemRequested) -> list[str]:
    candidates: list[str] = []
    if request.content_source.locator:
        candidates.append(request.content_source.locator)
    for key in ("path", "file_path", "filePath", "local_path", "localPath", "selector"):
        value = request.scan_options.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    for key in ("path", "file_path", "filePath", "local_path", "localPath"):
        value = request.read_hint.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    if request.object_identity:
        candidates.append(request.object_identity)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


class LocalPathReader(Reader):
    def resolve_path(self, request: ScanItemRequested) -> Path:
        if request.content_source.mode == "none":
            raise TerminalScanError("content_source_unavailable", "scan requires an available content source")
        candidates = coalesce_path_candidates(request)
        for raw in candidates:
            path = Path(raw).expanduser()
            if path.exists() and path.is_file():
                return path
        raise TerminalScanError(
            "local_content_path_not_found",
            "scan worker could not resolve a readable local file path",
            details={
                "objectIdentity": request.object_identity,
                "contentSourceMode": request.content_source.mode,
                "contentSourceLocator": request.content_source.locator,
                "candidates": candidates,
            },
        )

    async def acquire(self, request: ScanItemRequested) -> ReadResult:
        path = self.resolve_path(request)
        return ReadResult(
            local_path=path,
            details={
                "reader": "local_path",
                "resolvedPath": str(path),
            },
        )
