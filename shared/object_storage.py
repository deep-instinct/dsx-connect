from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    key: str
    uri: str | None = None


@dataclass(frozen=True)
class ObjectInfo:
    ref: ObjectRef
    size_bytes: int | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectScope:
    bucket: str
    prefix: str = ""
    filter: str = ""


class ObjectReader(Protocol):
    async def open_object(self, ref: ObjectRef) -> AsyncIterator[bytes]:
        ...


class ObjectWriter(Protocol):
    async def write_object(self, ref: ObjectRef, chunks: AsyncIterator[bytes]) -> int:
        ...


class ObjectDiscoverer(Protocol):
    async def list_objects(self, scope: ObjectScope) -> AsyncIterator[ObjectInfo]:
        ...
