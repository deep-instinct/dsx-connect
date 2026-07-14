import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

from pydantic import ValidationError

from dsx_connect_ng.config import ReaderSettings
from dsx_connect_ng.jobs.bus import InMemoryJobBus
from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.jobs.models import BatchJobSubmitRequest, ContentSource
from dsx_connect_ng.jobs.repository import InMemoryJobRepository
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.readers.cached import CachedArtifactReader
from dsx_connect_ng.readers.contracts import ArtifactRef, ConnectorProxyReadRequest, ConnectorProxyReadResponse, ReaderErrorPayload
from dsx_connect_ng.readers import gcs_native as gcs_native_module
from dsx_connect_ng.readers.gcs_native import GCSNativeReader, resolve_gcs_object_ref
from dsx_connect_ng.readers import proxy as proxy_module
from dsx_connect_ng.readers.base import TerminalScanError
from dsx_connect_ng.readers.proxy import ConnectorProxyReader, ConnectorProxyRuntimeConfig, build_legacy_connector_read_payload, http_connector_proxy_read
from dsx_connect_ng.readers.resolver import build_scan_reader
from dsx_connect_ng.workers import scan_worker


async def _collect_async_chunks(data) -> list[bytes]:
    return [chunk async for chunk in data]


def _scan_request_from_submitted_item(*, object_identity: str, payload: dict) -> ScanItemRequested:
    bus = InMemoryJobBus()
    service = JobService(repo=InMemoryJobRepository(), bus=bus)
    asyncio.run(
        service.submit_batch_job(
            BatchJobSubmitRequest(
                integration_id="integration-1",
                scope_id="scope-1",
                items=[
                    {
                        "object_identity": object_identity,
                        "payload": payload,
                    }
                ],
            )
        )
    )
    return ScanItemRequested.from_envelope(bus.snapshot()[0])


def test_reader_settings_accept_chunk_size_env(monkeypatch) -> None:
    monkeypatch.setenv("DSX_CONNECT_NG_READERS__CHUNK_SIZE_BYTES", "2097152")

    settings = ReaderSettings()

    assert settings.chunk_size_bytes == 2 * 1024 * 1024


def test_connector_proxy_read_request_can_be_built_from_scan_request() -> None:
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="sharepoint-prod",
        scope_id="scope-1",
        object_identity="drive:1/item:2",
        content_source=ContentSource(mode="original"),
        read_hint={"drive_id": "drive-1"},
    )

    payload = ConnectorProxyReadRequest.from_scan_request(request)

    assert payload.integration_id == "sharepoint-prod"
    assert payload.scope_id == "scope-1"
    assert payload.object_identity == "drive:1/item:2"
    assert payload.options == {}
    assert payload.preferred_modes == ["stream", "artifact_ref", "buffer"]


def test_connector_proxy_read_request_carries_scan_options_as_reader_options() -> None:
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="gcs-prod",
        object_identity="display-name",
        scan_options={"path": "bucket-a/object.pdf", "readerStrategy": "proxy"},
    )

    payload = ConnectorProxyReadRequest.from_scan_request(request)

    assert payload.options["path"] == "bucket-a/object.pdf"
    assert payload.options["readerStrategy"] == "proxy"


def test_connector_proxy_read_request_requires_integration_id() -> None:
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="drive:1/item:2",
    )

    try:
        ConnectorProxyReadRequest.from_scan_request(request)
    except ValueError as exc:
        assert "connector_proxy_reader_requires_integration_id" in str(exc)
    else:
        raise AssertionError("expected missing integration_id to fail")


def test_connector_proxy_read_response_requires_artifact_ref_for_artifact_mode() -> None:
    try:
        ConnectorProxyReadResponse(mode="artifact_ref")
    except ValidationError as exc:
        assert "artifact_ref_mode_requires_artifact_ref" in str(exc)
    else:
        raise AssertionError("expected missing artifact_ref to fail")


def test_connector_proxy_read_response_accepts_artifact_ref_shape() -> None:
    response = ConnectorProxyReadResponse(
        mode="artifact_ref",
        content_length=128,
        artifact_ref=ArtifactRef(
            kind="signed_url",
            locator="https://example.invalid/tmp/object-1",
            expires_at=datetime(2026, 5, 20, 22, 0, tzinfo=timezone.utc),
        ),
    )

    assert response.artifact_ref is not None
    assert response.artifact_ref.kind == "signed_url"


def test_reader_error_payload_captures_retryable_semantics() -> None:
    payload = ReaderErrorPayload(
        code="rate_limit",
        message="connector rate limit exceeded",
        retryable=True,
        details={"platform_status": 429},
    )

    assert payload.code == "rate_limit"
    assert payload.retryable is True
    assert payload.details["platform_status"] == 429


def test_build_legacy_connector_read_payload_maps_scan_request_shape() -> None:
    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="sharepoint-prod",
        scope_id="scope-1",
        object_identity="drive:1/item:2",
        content_source=ContentSource(mode="original", locator="drive:1/item:2"),
        read_hint={
            "location": "drive:1/item:2",
            "metainfo": "finance/bad.exe",
            "size_in_bytes": 123,
        },
    )

    payload = build_legacy_connector_read_payload(request, connector_url="http://connector")

    assert payload["location"] == "drive:1/item:2"
    assert payload["metainfo"] == "finance/bad.exe"
    assert payload["connector_url"] == "http://connector"
    assert payload["size_in_bytes"] == 123
    assert payload["scan_job_id"] == "job-1"


def test_build_legacy_connector_read_payload_prefers_payload_path_aliases() -> None:
    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="gcs-prod",
        scope_id="scope-1",
        object_identity="BadMojoResume",
        content_source=ContentSource(mode="original"),
        read_hint={"objectIdentity": "BadMojoResume"},
        options={"path": "bucket-a/BadMojoResume", "sizeInBytes": 69},
    )

    payload = build_legacy_connector_read_payload(request, connector_url="http://connector")

    assert payload["location"] == "bucket-a/BadMojoResume"
    assert payload["metainfo"] == "BadMojoResume"
    assert payload["size_in_bytes"] == 69


def test_filesystem_batch_payload_path_flows_to_legacy_connector_location() -> None:
    request = _scan_request_from_submitted_item(
        object_identity="proxy-reader-sample.txt",
        payload={
            "readerStrategy": "proxy",
            "path": "/tmp/dsx-connect-ng/proxy-reader-sample.txt",
        },
    )

    proxy_request = ConnectorProxyReadRequest.from_scan_request(request)
    payload = build_legacy_connector_read_payload(proxy_request, connector_url="http://127.0.0.1:8620/filesystem")

    assert proxy_request.options["path"] == "/tmp/dsx-connect-ng/proxy-reader-sample.txt"
    assert payload["location"] == "/tmp/dsx-connect-ng/proxy-reader-sample.txt"
    assert payload["metainfo"] == "proxy-reader-sample.txt"
    assert payload["scan_job_id"] == request.job_id


def test_gcs_batch_payload_path_flows_to_legacy_connector_location() -> None:
    request = _scan_request_from_submitted_item(
        object_identity="BadMojoResume",
        payload={
            "readerStrategy": "proxy",
            "path": "BadMojoResume",
        },
    )

    proxy_request = ConnectorProxyReadRequest.from_scan_request(request)
    payload = build_legacy_connector_read_payload(proxy_request, connector_url="http://127.0.0.1:8630/google-cloud-storage-connector")

    assert proxy_request.options["path"] == "BadMojoResume"
    assert payload["location"] == "BadMojoResume"
    assert payload["metainfo"] == "BadMojoResume"
    assert payload["scan_job_id"] == request.job_id


def test_native_gcs_reader_resolves_protected_scope_bucket_and_relative_path() -> None:
    request = _scan_request_from_submitted_item(
        object_identity="lg-test-01/benchmarks/1kdocs/a.pdf",
        payload={
            "readerStrategy": "native",
            "scopeSelector": "lg-test-01",
            "path": "benchmarks/1kdocs/a.pdf",
        },
    )

    resolved = resolve_gcs_object_ref(request)

    assert resolved.bucket == "lg-test-01"
    assert resolved.key == "benchmarks/1kdocs/a.pdf"


def test_native_gcs_reader_resolves_prefixed_scope_path() -> None:
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="bucket-a/prefix-a/object.pdf",
        scan_options={
            "readerStrategy": "native",
            "scopeSelector": "bucket-a/prefix-a",
            "path": "object.pdf",
        },
    )

    resolved = resolve_gcs_object_ref(request)

    assert resolved.bucket == "bucket-a"
    assert resolved.key == "prefix-a/object.pdf"


def test_native_gcs_reader_streams_and_closes_blob() -> None:
    class FakeStream:
        def __init__(self) -> None:
            self.chunks = [b"abc", b"def", b""]
            self.closed = False

        def read(self, _size: int) -> bytes:
            return self.chunks.pop(0)

        def close(self) -> None:
            self.closed = True

    stream = FakeStream()
    seen: dict[str, str] = {}

    class FakeBlob:
        def open(self, mode: str, *, chunk_size: int):
            assert mode == "rb"
            assert chunk_size == 4
            return stream

    class FakeBucket:
        def blob(self, key: str) -> FakeBlob:
            seen["key"] = key
            return FakeBlob()

    class FakeClient:
        def bucket(self, bucket: str) -> FakeBucket:
            seen["bucket"] = bucket
            return FakeBucket()

    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="bucket-a/object.pdf",
        scan_options={"readerStrategy": "native", "sizeInBytes": 6},
    )
    reader = GCSNativeReader(client_factory=lambda: FakeClient(), chunk_size=4)

    result = asyncio.run(reader.acquire(request))
    chunks = asyncio.run(_collect_async_chunks(result.content_stream))

    assert chunks == [b"abc", b"def"]
    assert stream.closed is True
    assert result.content_length == 6
    assert result.details["reader"] == "gcs_native"
    assert seen == {"bucket": "bucket-a", "key": "object.pdf"}


def test_native_gcs_default_client_is_cached(monkeypatch) -> None:
    created: list[object] = []

    def fake_uncached_client():
        client = object()
        created.append(client)
        return client

    gcs_native_module.reset_default_storage_client()
    monkeypatch.setattr(gcs_native_module, "_uncached_storage_client", fake_uncached_client)

    first = gcs_native_module._default_storage_client()
    second = gcs_native_module._default_storage_client()
    gcs_native_module.reset_default_storage_client()
    third = gcs_native_module._default_storage_client()
    gcs_native_module.reset_default_storage_client()

    assert first is second
    assert third is not first
    assert created == [first, third]


def test_http_connector_proxy_read_downloads_binary_to_local_artifact(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": "3",
            }
            self._chunks = [b"abc", b""]

        def read(self, _size: int = -1) -> bytes:
            return self._chunks.pop(0)

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_urlopen(req: Request, timeout: float):
        assert timeout == 5.0
        seen["url"] = req.full_url
        seen["body"] = req.data.decode("utf-8") if req.data else ""
        return FakeResponse()

    monkeypatch.setattr(proxy_module, "urlopen", fake_urlopen)

    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        scope_id="scope-1",
        object_identity="/finance/bad.exe",
        content_source=ContentSource(mode="original", locator="/finance/bad.exe"),
        read_hint={"location": "/finance/bad.exe", "metainfo": "bad.exe"},
    )
    config = ConnectorProxyRuntimeConfig(
        endpoint_url="http://127.0.0.1:8620/filesystem/read_file",
        auth_mode="none",
        timeout_seconds=5.0,
    )

    response = asyncio.run(http_connector_proxy_read(request, config))

    assert response.mode == "artifact_ref"
    assert response.artifact_ref is not None
    assert response.artifact_ref.kind == "local_path"
    path = Path(response.artifact_ref.locator)
    assert path.exists()
    assert path.read_bytes() == b"abc"
    assert response.content_length == 3
    assert seen["url"] == "http://127.0.0.1:8620/filesystem/read_file"
    assert json.loads(seen["body"]) == {
        "location": "/finance/bad.exe",
        "metainfo": "bad.exe",
        "connector_url": "http://127.0.0.1:8620/filesystem",
        "size_in_bytes": None,
        "scan_job_id": "job-1",
    }
    path.unlink()


def test_http_connector_proxy_stream_yields_binary_without_local_artifact(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": "6",
            }
            self._chunks = [b"abc", b"def", b""]
            self.closed = False
            self.chunk_sizes: list[int] = []
            self.status_code = 200

        async def aiter_bytes(self, chunk_size: int):
            self.chunk_sizes.append(chunk_size)
            for chunk in self._chunks:
                if chunk:
                    yield chunk

        async def aread(self) -> bytes:
            return b""

    class FakeStream:
        def __init__(self, response: FakeResponse) -> None:
            self.response = response

        async def __aenter__(self) -> FakeResponse:
            return self.response

        async def __aexit__(self, exc_type, exc, tb) -> None:
            self.response.closed = True

    class FakeClient:
        def stream(self, method: str, url: str, *, content: bytes, headers: dict):
            seen["method"] = method
            seen["url"] = url
            seen["body"] = content.decode("utf-8")
            seen["headers"] = headers
            return FakeStream(fake_response)

    fake_response = FakeResponse()

    monkeypatch.setattr(proxy_module, "_get_async_proxy_client", lambda config: FakeClient())

    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        object_identity="/finance/a.txt",
        content_source=ContentSource(mode="original", locator="/finance/a.txt"),
        read_hint={"location": "/finance/a.txt", "sizeInBytes": 6},
    )
    config = ConnectorProxyRuntimeConfig(
        endpoint_url="http://127.0.0.1:8620/filesystem/read_file",
        auth_mode="none",
        timeout_seconds=5.0,
    )

    read_result = asyncio.run(proxy_module.http_connector_proxy_stream(request, config, chunk_size=4))
    assert read_result.local_path is None
    assert read_result.content_stream is not None
    assert read_result.content_length == 6
    assert read_result.details["source"] == "connector_proxy_http_stream"

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in read_result.content_stream])

    assert asyncio.run(collect()) == b"abcdef"
    assert fake_response.chunk_sizes == [4]
    assert fake_response.closed is True
    assert seen["method"] == "POST"
    assert seen["url"] == "http://127.0.0.1:8620/filesystem/read_file"
    assert json.loads(seen["body"])["location"] == "/finance/a.txt"


def test_http_connector_proxy_read_maps_structured_connector_json_error(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def read(self, _size: int = -1) -> bytes:
            return json.dumps({"status": "error", "errorCode": "object_not_found", "errorMessage": "missing"}).encode("utf-8")

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(proxy_module, "urlopen", lambda req, timeout: FakeResponse())

    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="gcs-prod",
        object_identity="missing-object",
        content_source=ContentSource(mode="original"),
    )
    config = ConnectorProxyRuntimeConfig(endpoint_url="http://127.0.0.1:8620/filesystem/read_file")

    try:
        asyncio.run(http_connector_proxy_read(request, config))
    except TerminalScanError as exc:
        assert exc.code == "object_not_found"
        assert exc.details["response"]["errorMessage"] == "missing"
    else:
        raise AssertionError("expected structured connector error to fail")


def test_http_connector_proxy_read_maps_forbidden_to_permission_error(monkeypatch) -> None:
    def fake_urlopen(req: Request, timeout: float):
        raise HTTPError(
            req.full_url,
            403,
            "Forbidden",
            hdrs={},
            fp=SimpleNamespace(read=lambda: b'{"message":"denied"}', close=lambda: None),
        )

    monkeypatch.setattr(proxy_module, "urlopen", fake_urlopen)

    request = ConnectorProxyReadRequest(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="gcs-prod",
        object_identity="forbidden-object",
        content_source=ContentSource(mode="original"),
    )
    config = ConnectorProxyRuntimeConfig(endpoint_url="http://127.0.0.1:8620/filesystem/read_file")

    try:
        asyncio.run(http_connector_proxy_read(request, config))
    except TerminalScanError as exc:
        assert exc.code == "permission_error"
        assert exc.details["statusCode"] == 403
    else:
        raise AssertionError("expected forbidden connector response to fail")


def test_connector_proxy_reader_local_stub_resolves_payload_path_option(tmp_path) -> None:
    artifact = tmp_path / "payload-path.bin"
    artifact.write_bytes(b"payload")
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="filesystem-local",
        object_identity="logical-name",
        content_source=ContentSource(mode="original"),
        scan_options={"path": str(artifact)},
    )

    result = asyncio.run(ConnectorProxyReader(proxy_module.local_stub_connector_read).acquire(request))

    assert result.local_path == artifact
    assert result.content_length == len(b"payload")
    assert result.cleanup_local_path is False
    assert result.details["reader"] == "connector_proxy"


def test_execute_scan_via_dsxa_exposes_reader_content_metadata(monkeypatch, tmp_path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"abc")
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="integration-1",
        object_identity="sample.bin",
    )

    class FakeReader:
        async def acquire(self, _request):
            return SimpleNamespace(
                local_path=file_path,
                content_length=3,
                details={
                    "reader": "connector_proxy",
                    "proxyResponse": {
                        "content_type": "application/octet-stream",
                    },
                },
            )

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def scan_binary_stream(self, data, **kwargs):
            assert b"".join([chunk async for chunk in data]) == b"abc"
            file_info = SimpleNamespace(
                model_dump=lambda mode: {
                    "file_hash": "hash",
                    "file_type": "Binary",
                    "container_hash": None,
                    "file_size_in_bytes": 3,
                    "additional_office_data": None,
                }
            )
            return SimpleNamespace(
                scan_guid="guid-1",
                verdict=SimpleNamespace(value="Benign"),
                verdict_details=SimpleNamespace(model_dump=lambda mode, by_alias: {"event_description": "ok"}),
                file_info=file_info,
                x_custom_metadata=None,
                last_update_time=None,
                protected_entity=None,
                scan_duration_in_microseconds=1,
                container_files_scanned=None,
                container_files_scanned_size=None,
            )

    monkeypatch.setattr(scan_worker.settings.scanner, "base_url", "http://scanner")
    monkeypatch.setattr(
        scan_worker,
        "_import_dsxa_client",
        lambda: (FakeClient, object, Exception, RuntimeError, RuntimeError, RuntimeError, RuntimeError),
    )

    asyncio.run(scan_worker.execute_scan_via_dsxa(request, FakeReader()))

    metadata = request.scan_options["_dsx_scanner_metadata"]
    assert metadata["contentLength"] == 3
    assert metadata["contentType"] == "application/octet-stream"


def test_cached_artifact_reader_resolves_existing_cached_path(tmp_path) -> None:
    artifact = tmp_path / "scan.bin"
    artifact.write_bytes(b"cached")
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        content_source=ContentSource(mode="cached", locator=str(artifact)),
    )

    result = asyncio.run(CachedArtifactReader().acquire(request))

    assert result.local_path == artifact
    assert result.cleanup_local_path is False
    assert result.details["reader"] == "cached_artifact"


def test_cached_artifact_reader_rejects_non_cached_source() -> None:
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        content_source=ContentSource(mode="original"),
    )

    try:
        asyncio.run(CachedArtifactReader().acquire(request))
    except TerminalScanError as exc:
        assert exc.code == "cached_content_source_required"
    else:
        raise AssertionError("expected non-cached source to fail")


def test_build_scan_reader_selects_cached_strategy(tmp_path) -> None:
    artifact = tmp_path / "scan.bin"
    artifact.write_bytes(b"cached")
    request = ScanItemRequested(
        job_id="job-1",
        job_item_id="item-1",
        object_identity="/finance/a.pdf",
        content_source=ContentSource(mode="cached", locator=str(artifact)),
        scan_options={"readerStrategy": "cached"},
    )

    reader = build_scan_reader(request)

    assert isinstance(reader, CachedArtifactReader)
