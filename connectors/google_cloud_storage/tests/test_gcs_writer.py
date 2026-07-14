from __future__ import annotations

import asyncio
import io

from connectors.google_cloud_storage.gcs_discoverer import GCSDiscoverer
from connectors.google_cloud_storage.gcs_reader import GCSReader
from connectors.google_cloud_storage.gcs_writer import GCSWriter
from shared.object_storage import ObjectRef, ObjectScope


class FakeGCSClient:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []
        self.ready_buckets: list[str | None] = []
        self.objects: dict[tuple[str, str], bytes] = {}
        self.listed: list[tuple[str, str, str]] = []

    def upload_bytes(self, content, key: str, bucket: str) -> None:
        self.uploads.append((bucket, key, content.read()))

    def ensure_ready(self, bucket: str | None = None) -> None:
        self.ready_buckets.append(bucket)

    def get_object(self, bucket: str, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[(bucket, key)])

    def open_object_stream(self, bucket: str, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[(bucket, key)])

    def keys(self, bucket: str, base_prefix: str = "", filter_str: str = ""):
        self.listed.append((bucket, base_prefix, filter_str))
        yield {"Key": f"{base_prefix.rstrip('/')}/a.txt".lstrip("/"), "Size": 5}


async def _chunks():
    yield b"alpha"
    yield b"bravo"


def test_gcs_writer_uploads_object_chunks() -> None:
    client = FakeGCSClient()
    writer = GCSWriter(client=client)

    written = asyncio.run(
        writer.write_object(
            ObjectRef(bucket="clean-bucket", key="archive/file.txt"),
            _chunks(),
        )
    )

    assert written == len(b"alphabravo")
    assert client.uploads == [("clean-bucket", "archive/file.txt", b"alphabravo")]


def test_gcs_writer_validates_bucket_access() -> None:
    client = FakeGCSClient()
    writer = GCSWriter(client=client)

    writer.validate(bucket="clean-bucket")

    assert client.ready_buckets == ["clean-bucket"]


def test_gcs_reader_opens_object_chunks() -> None:
    client = FakeGCSClient()
    client.objects[("clean-bucket", "archive/file.txt")] = b"alphabravo"
    reader = GCSReader(client=client, chunk_size=5)

    chunks = asyncio.run(_collect(reader.open_object(ObjectRef(bucket="clean-bucket", key="archive/file.txt"))))

    assert chunks == [b"alpha", b"bravo"]


def test_gcs_discoverer_lists_object_info() -> None:
    client = FakeGCSClient()
    discoverer = GCSDiscoverer(client=client)

    objects = asyncio.run(_collect(discoverer.list_objects(ObjectScope(bucket="clean-bucket", prefix="archive", filter="*.txt"))))

    assert client.listed == [("clean-bucket", "archive", "*.txt")]
    assert objects[0].ref.bucket == "clean-bucket"
    assert objects[0].ref.key == "archive/a.txt"
    assert objects[0].ref.uri == "gs://clean-bucket/archive/a.txt"
    assert objects[0].size_bytes == 5


async def _collect(chunks):
    return [chunk async for chunk in chunks]
