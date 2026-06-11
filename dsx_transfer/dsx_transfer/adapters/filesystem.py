from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from dsx_transfer.contracts import SinkAdapter, SourceAdapter
from dsx_transfer.models import TransferItem, TransferPlan


def _file_uri(path: Path) -> str:
    return path.resolve().as_uri()


class FilesystemSourceAdapter(SourceAdapter):
    def __init__(self, root: str | Path, *, chunk_size: int = 1024 * 1024) -> None:
        self.root = Path(root).resolve()
        self.chunk_size = chunk_size

    async def plan(self, *, destination_uri: str, transfer_id: str, policy_id: str | None = None) -> TransferPlan:
        items: list[TransferItem] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            stat = path.stat()
            destination = destination_uri.rstrip("/") + "/" + relative
            items.append(
                TransferItem(
                    source_uri=_file_uri(path),
                    destination_uri=destination,
                    object_identity=relative,
                    size_bytes=stat.st_size,
                    metadata={
                        "source_path": str(path),
                        "relative_path": relative,
                        "mtime_ns": stat.st_mtime_ns,
                    },
                )
            )
        return TransferPlan(
            transfer_id=transfer_id,
            source_uri=_file_uri(self.root),
            destination_uri=destination_uri,
            policy_id=policy_id,
            items=items,
        )

    async def open_item(self, item: TransferItem) -> AsyncIterator[bytes]:
        source_path = item.metadata.get("source_path")
        if not source_path:
            raise ValueError("filesystem_source_path_missing")
        with Path(source_path).open("rb") as handle:
            while True:
                chunk = handle.read(self.chunk_size)
                if not chunk:
                    break
                yield chunk


class FilesystemSinkAdapter(SinkAdapter):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    async def write_item(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> int:
        relative = item.metadata.get("relative_path") or item.object_identity
        destination = (self.root / str(relative)).resolve()
        destination.relative_to(self.root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with destination.open("wb") as handle:
            async for chunk in chunks:
                bytes_written += len(chunk)
                handle.write(chunk)
        return bytes_written
