from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.base import ReadResult, Reader, TerminalScanError


_BUCKET_KEYS = ("bucket", "bucketName", "bucket_name", "gcsBucket", "gcs_bucket")
_KEY_KEYS = ("key", "objectKey", "object_key", "path", "location", "selector")
_DEFAULT_CLIENT: Any | None = None
_DEFAULT_CLIENT_LOCK = threading.Lock()


@dataclass(frozen=True)
class GCSObjectRef:
    bucket: str
    key: str


def _first_non_empty_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _split_bucket_scope(value: str | None) -> tuple[str, str]:
    raw = str(value or "").strip().strip("/")
    if not raw:
        return "", ""
    if "/" not in raw:
        return raw, ""
    bucket, prefix = raw.split("/", 1)
    return bucket.strip(), prefix.strip("/")


def _join_key(prefix: str, key: str) -> str:
    prefix = prefix.strip("/")
    key = key.strip("/")
    if not prefix:
        return key
    if not key:
        return prefix
    if key == prefix or key.startswith(f"{prefix}/"):
        return key
    return f"{prefix}/{key}"


def _size_hint(request: ScanItemRequested) -> int | None:
    for source in (request.scan_options, request.read_hint):
        for key in ("sizeInBytes", "size_in_bytes", "contentLength", "content_length"):
            value = source.get(key)
            if isinstance(value, int):
                return value
    return None


def resolve_gcs_object_ref(request: ScanItemRequested) -> GCSObjectRef:
    bucket = _first_non_empty_string(
        *(request.scan_options.get(key) for key in _BUCKET_KEYS),
        *(request.read_hint.get(key) for key in _BUCKET_KEYS),
    )
    key = _first_non_empty_string(
        *(request.scan_options.get(key) for key in _KEY_KEYS),
        *(request.read_hint.get(key) for key in _KEY_KEYS),
        request.content_source.locator,
        request.object_identity,
    )
    scope_bucket, scope_prefix = _split_bucket_scope(request.scan_options.get("scopeSelector"))
    if not bucket and scope_bucket:
        bucket = scope_bucket
    if not bucket and key:
        candidate_bucket, candidate_key = _split_bucket_scope(key)
        if candidate_bucket and candidate_key:
            bucket = candidate_bucket
            key = candidate_key
    if bucket and key and key.strip("/").startswith(f"{bucket.strip('/')}/"):
        key = key.strip("/").split("/", 1)[1]
    if scope_prefix and key:
        key = _join_key(scope_prefix, key)
    if not bucket or not key:
        raise TerminalScanError(
            "invalid_read_context",
            "native GCS reader requires a bucket and object key",
            details={
                "objectIdentity": request.object_identity,
                "scopeSelector": request.scan_options.get("scopeSelector"),
                "contentSourceLocator": request.content_source.locator,
                "scanOptions": request.scan_options,
                "readHint": request.read_hint,
            },
        )
    return GCSObjectRef(bucket=bucket.strip("/"), key=key.strip("/"))


def _default_storage_client():
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is not None:
        return _DEFAULT_CLIENT
    with _DEFAULT_CLIENT_LOCK:
        if _DEFAULT_CLIENT is not None:
            return _DEFAULT_CLIENT
        _DEFAULT_CLIENT = _uncached_storage_client()
        return _DEFAULT_CLIENT


def reset_default_storage_client() -> None:
    global _DEFAULT_CLIENT
    with _DEFAULT_CLIENT_LOCK:
        _DEFAULT_CLIENT = None


def _uncached_storage_client():
    try:
        from google.cloud import storage
    except Exception as exc:  # pragma: no cover - exercised only without optional dependency
        raise TerminalScanError(
            "native_gcs_dependency_missing",
            "google-cloud-storage is required for native GCS reads",
        ) from exc
    return storage.Client()


def _map_gcs_open_error(exc: Exception, *, ref: GCSObjectRef) -> Exception:
    name = exc.__class__.__name__.lower()
    message = str(exc)
    details = {"bucket": ref.bucket, "key": ref.key}
    if isinstance(exc, FileNotFoundError) or "notfound" in name or "not found" in message.lower():
        return TerminalScanError("object_not_found", "GCS object was not found", details=details)
    if "forbidden" in name or "permission" in name:
        return TerminalScanError("permission_error", "GCS object read was denied", details=details)
    if "unauthorized" in name or "auth" in name:
        return TerminalScanError("auth_error", "GCS authentication failed", details=details)
    return exc


async def _stream_gcs_chunks(stream: BinaryIO, *, chunk_size: int = 1024 * 1024):
    try:
        while True:
            chunk = await asyncio.to_thread(stream.read, chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        await asyncio.to_thread(stream.close)


class GCSNativeReader(Reader):
    def __init__(self, *, client_factory: Callable[[], Any] | None = None, chunk_size: int = 1024 * 1024) -> None:
        self.client_factory = client_factory or _default_storage_client
        self.chunk_size = chunk_size

    async def acquire(self, request: ScanItemRequested) -> ReadResult:
        if request.content_source.mode == "none":
            raise TerminalScanError("content_source_unavailable", "native GCS reader requires an available content source")
        ref = resolve_gcs_object_ref(request)
        try:
            client = self.client_factory()
            blob = client.bucket(ref.bucket).blob(ref.key)
            stream = await asyncio.to_thread(blob.open, "rb", chunk_size=self.chunk_size)
        except Exception as exc:
            raise _map_gcs_open_error(exc, ref=ref) from exc
        return ReadResult(
            content_stream=_stream_gcs_chunks(stream, chunk_size=self.chunk_size),
            content_length=_size_hint(request),
            details={
                "reader": "gcs_native",
                "bucket": ref.bucket,
                "key": ref.key,
            },
        )
