from __future__ import annotations

from dsx_connect_ng.config import settings
from dsx_connect_ng.result_sink.base import ResultSink
from dsx_connect_ng.result_sink.json_lines import JsonLinesResultSink
from dsx_connect_ng.result_sink.stdout import StdoutResultSink


def build_result_sink() -> ResultSink:
    if settings.result_sink.backend == "stdout":
        return StdoutResultSink()
    if settings.result_sink.backend == "json_lines":
        return JsonLinesResultSink(settings.result_sink.path)
    raise ValueError(f"unsupported_result_sink_backend:{settings.result_sink.backend}")
