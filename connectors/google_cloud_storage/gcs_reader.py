from __future__ import annotations

import asyncio
from typing import AsyncIterator

from connectors.google_cloud_storage.gcs_client import GCSClient, CHUNK_SIZE
from shared.object_storage import ObjectRef


class GCSReader:
    def __init__(self, client: GCSClient | None = None, *, chunk_size: int = CHUNK_SIZE) -> None:
        self.client = client or GCSClient()
        self.chunk_size = chunk_size

    def validate(self, *, bucket: str | None = None) -> None:
        self.client.ensure_ready(bucket=bucket)

    async def open_object(self, ref: ObjectRef) -> AsyncIterator[bytes]:
        stream = self.client.open_object_stream(ref.bucket, ref.key)
        try:
            while True:
                chunk = await asyncio.to_thread(stream.read, self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(stream.close)
