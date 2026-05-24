from __future__ import annotations

from abc import ABC, abstractmethod

from dsx_connect_ng.result_sink.models import ResultSinkEvent


class ResultSink(ABC):
    @abstractmethod
    async def emit(self, event: ResultSinkEvent) -> None:
        raise NotImplementedError
