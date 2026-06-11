from __future__ import annotations

from pathlib import Path

from dsx_transfer.contracts import AuditSink
from dsx_transfer.models import AuditEvent


class JsonLinesAuditSink(AuditSink):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def emit(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json())
            handle.write("\n")
