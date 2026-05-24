from __future__ import annotations

from pathlib import Path

from dsx_connect_ng.result_sink.base import ResultSink
from dsx_connect_ng.result_sink.models import ResultSinkEvent


class JsonLinesResultSink(ResultSink):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    async def emit(self, event: ResultSinkEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json(by_alias=True, exclude_none=True))
            handle.write("\n")
