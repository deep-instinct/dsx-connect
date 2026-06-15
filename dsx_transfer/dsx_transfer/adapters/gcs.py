from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from dsx_transfer.contracts import ObjectRef, ObjectWriter, SinkAdapter
from dsx_transfer.models import TransferItem


@dataclass(frozen=True)
class GcsUri:
    bucket: str
    prefix: str = ""

    @property
    def uri(self) -> str:
        if self.prefix:
            return f"gs://{self.bucket}/{self.prefix}"
        return f"gs://{self.bucket}"


def parse_gcs_uri(value: str) -> GcsUri:
    if not value.startswith("gs://"):
        raise ValueError(f"GCS URI must start with gs://: {value!r}")
    remainder = value[len("gs://") :]
    bucket, separator, prefix = remainder.partition("/")
    if not bucket:
        raise ValueError(f"GCS URI is missing a bucket name: {value!r}")
    return GcsUri(bucket=bucket, prefix=prefix.strip("/")) if separator else GcsUri(bucket=bucket)


class GcsSinkAdapter(SinkAdapter):
    def __init__(
        self,
        destination: str | GcsUri,
        *,
        writer: ObjectWriter | None = None,
        client: Any | None = None,
    ) -> None:
        self.destination = parse_gcs_uri(destination) if isinstance(destination, str) else destination
        self.writer = writer or _default_gcs_writer(client=client)
        _validate_writer(self.writer, bucket=self.destination.bucket)

    async def write_item(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> int:
        relative = str(item.metadata.get("relative_path") or item.object_identity).lstrip("/")
        key = "/".join(part for part in [self.destination.prefix, relative] if part)
        return await self.writer.write_object(
            ObjectRef(
                bucket=self.destination.bucket,
                key=key,
                uri=f"gs://{self.destination.bucket}/{key}",
            ),
            chunks,
        )


def _default_gcs_writer(*, client: Any | None = None) -> ObjectWriter:
    try:
        from connectors.google_cloud_storage.gcs_writer import GCSWriter
    except ImportError as exc:
        raise RuntimeError(
            "GCS transfers require the google_cloud_storage connector package."
        ) from exc
    try:
        return GCSWriter(client=client)
    except Exception as exc:
        raise RuntimeError(
            "GCS transfers require Google Application Default Credentials. "
            "Run `gcloud auth application-default login` for local demos, "
            "or set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON file."
        ) from exc


def _validate_writer(writer: ObjectWriter, *, bucket: str) -> None:
    validate = getattr(writer, "validate", None)
    if validate is None:
        return
    try:
        validate(bucket=bucket)
    except Exception as exc:
        raise RuntimeError(
            "GCS transfers require Google Application Default Credentials and bucket access. "
            "Run `gcloud auth application-default login` for local demos, "
            "or set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON file."
        ) from exc
