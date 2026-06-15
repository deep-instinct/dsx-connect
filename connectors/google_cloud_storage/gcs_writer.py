from __future__ import annotations

import io
from typing import AsyncIterator

from connectors.google_cloud_storage.gcs_client import GCSClient
from shared.object_storage import ObjectRef


class GCSWriter:
    def __init__(self, client: GCSClient | None = None) -> None:
        self.client = client or GCSClient()

    def validate(self, *, bucket: str | None = None) -> None:
        self.client.ensure_ready(bucket=bucket)

    async def write_object(self, ref: ObjectRef, chunks: AsyncIterator[bytes]) -> int:
        content = io.BytesIO()
        bytes_written = 0
        async for chunk in chunks:
            bytes_written += len(chunk)
            content.write(chunk)
        content.seek(0)
        self.client.upload_bytes(content, key=ref.key, bucket=ref.bucket)
        return bytes_written
