import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request

from pydantic import ValidationError

from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.jobs.models import ContentSource
from dsx_connect_ng.readers.cached import CachedArtifactReader
from dsx_connect_ng.readers.contracts import ArtifactRef, ConnectorProxyReadRequest, ConnectorProxyReadResponse, ReaderErrorPayload
from dsx_connect_ng.readers import proxy as proxy_module
from dsx_connect_ng.readers.base import TerminalScanError
from dsx_connect_ng.readers.proxy import ConnectorProxyRuntimeConfig, build_legacy_connector_read_payload, http_connector_proxy_read
from dsx_connect_ng.readers.resolver import build_scan_reader


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
    assert payload.preferred_modes == ["stream", "artifact_ref", "buffer"]


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
