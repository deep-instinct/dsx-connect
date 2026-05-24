from __future__ import annotations

import sys

from dsx_connect_ng.result_sink.base import ResultSink
from dsx_connect_ng.result_sink.models import ResultSinkEvent


class StdoutResultSink(ResultSink):
    async def emit(self, event: ResultSinkEvent) -> None:
        sys.stdout.write(event.model_dump_json(by_alias=True, exclude_none=True))
        sys.stdout.write("\n")
        sys.stdout.flush()
