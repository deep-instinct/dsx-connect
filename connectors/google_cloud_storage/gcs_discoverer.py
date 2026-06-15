from __future__ import annotations

from typing import AsyncIterator

from connectors.google_cloud_storage.gcs_client import GCSClient
from shared.object_storage import ObjectInfo, ObjectRef, ObjectScope


class GCSDiscoverer:
    def __init__(self, client: GCSClient | None = None) -> None:
        self.client = client or GCSClient()

    def validate(self, *, bucket: str | None = None) -> None:
        self.client.ensure_ready(bucket=bucket)

    async def list_objects(self, scope: ObjectScope) -> AsyncIterator[ObjectInfo]:
        for item in self.client.keys(scope.bucket, base_prefix=scope.prefix, filter_str=scope.filter):
            key = item["Key"]
            yield ObjectInfo(
                ref=ObjectRef(
                    bucket=scope.bucket,
                    key=key,
                    uri=f"gs://{scope.bucket}/{key}",
                ),
                size_bytes=item.get("Size"),
            )
