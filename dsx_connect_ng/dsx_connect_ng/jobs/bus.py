from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


@runtime_checkable
class PublishableMessage(Protocol):
    def model_dump(self, *, mode: str = "python") -> dict:
        ...


class JobBus(ABC):
    @abstractmethod
    async def publish(self, job: PublishableMessage) -> None:
        raise NotImplementedError

    @abstractmethod
    async def status(self) -> dict:
        raise NotImplementedError


class InMemoryJobBus(JobBus):
    def __init__(self) -> None:
        self._published: list[PublishableMessage] = []

    async def publish(self, job: PublishableMessage) -> None:
        self._published.append(job)

    async def status(self) -> dict:
        return {
            "backend": "memory",
            "published_count": len(self._published),
        }

    def snapshot(self) -> list[PublishableMessage]:
        return list(self._published)
