from __future__ import annotations

from pathlib import Path

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.base import ReadResult, Reader, TerminalScanError


class CachedArtifactReader(Reader):
    """Resolve previously preserved content from normalized cached-source state."""

    def resolve_path(self, request: ScanItemRequested) -> Path:
        source = request.content_source
        if source.mode != "cached":
            raise TerminalScanError(
                "cached_content_source_required",
                "cached reader requires content_source.mode=cached",
                details={"content_source_mode": source.mode},
            )
        locator = source.locator
        if not locator:
            raise TerminalScanError(
                "cached_locator_required",
                "cached reader requires content_source.locator",
            )
        path = Path(locator).expanduser()
        if not path.exists():
            raise TerminalScanError(
                "cached_artifact_not_found",
                f"cached artifact not found: {path}",
                details={"locator": str(path)},
            )
        if not path.is_file():
            raise TerminalScanError(
                "cached_artifact_not_file",
                f"cached artifact is not a file: {path}",
                details={"locator": str(path)},
            )
        return path

    async def acquire(self, request: ScanItemRequested) -> ReadResult:
        path = self.resolve_path(request)
        return ReadResult(
            local_path=path,
            details={
                "reader": "cached_artifact",
                "content_source_mode": request.content_source.mode,
            },
        )
