from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterable, Awaitable, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config
from dsx_connect_ng.control_plane.models import utcnow
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.contracts import ScanItemRequested
from dsx_connect_ng.readers.base import ReadResult, Reader, TerminalScanError
from dsx_connect_ng.readers.contracts import ArtifactRef, ConnectorProxyReadRequest, ConnectorProxyReadResponse
from shared.auth.hmac import make_hmac_header


ConnectorProxyExecutor = Callable[[ConnectorProxyReadRequest], Awaitable[ConnectorProxyReadResponse | ReadResult]]
_READ_PATH_KEYS = ("path", "file_path", "filePath", "local_path", "localPath", "selector", "location")


@dataclass(frozen=True)
class ConnectorProxyRuntimeConfig:
    endpoint_url: str
    auth_mode: str = "none"
    header_name: str | None = None
    header_value: str | None = None
    hmac_key_id: str | None = None
    hmac_secret: str | None = None
    timeout_seconds: float = 30.0


def _coalesce_local_proxy_candidates(request: ConnectorProxyReadRequest) -> list[str]:
    candidates: list[str] = []
    if request.content_source.locator:
        candidates.append(request.content_source.locator)
    for source in (request.read_hint, request.options):
        for key in _READ_PATH_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    if request.object_identity:
        candidates.append(request.object_identity)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _first_non_empty_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
    return None


def _normalize_registered_connector_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"0.0.0.0", "::"}:
        return base_url
    netloc = "127.0.0.1"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _live_connector_proxy_endpoint(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService,
) -> str | None:
    if not request.integration_id:
        return None
    instances = [
        instance
        for instance in control_plane.list_connector_instances(integration_id=request.integration_id)
        if instance.expires_at > utcnow() and instance.capabilities.get("read") is not False
    ]
    if not instances:
        return None
    priority = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
    instance = sorted(instances, key=lambda item: priority.get(item.health, 99))[0]
    return f"{_normalize_registered_connector_base_url(instance.base_url).rstrip('/')}/read_file"


def resolve_connector_proxy_runtime_config(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> ConnectorProxyRuntimeConfig:
    if control_plane is None or not request.integration_id:
        raise TerminalScanError(
            "connector_proxy_config_missing",
            "proxy reader strategy requires integration-level connector proxy configuration",
        )
    integration = control_plane.get_integration_or_404(request.integration_id)
    runtime_config = parse_integration_runtime_config(integration.config)
    proxy = runtime_config.reader.proxy if runtime_config.reader and runtime_config.reader.proxy else None

    endpoint_url = proxy.endpoint_url if proxy else None
    if not endpoint_url:
        endpoint_url = _live_connector_proxy_endpoint(request, control_plane=control_plane)
    if not endpoint_url:
        base_url = proxy.base_url if proxy else None
        connector_name = proxy.connector_name if proxy else None
        if base_url and connector_name:
            endpoint_url = f"{str(base_url).rstrip('/')}/{str(connector_name).strip('/')}/read_file"
    if not endpoint_url:
        raise TerminalScanError(
            "connector_proxy_config_missing",
            "integration reader.proxy config must define endpoint_url or base_url + connector_name",
            details={"integrationId": request.integration_id},
        )

    timeout = proxy.timeout_seconds if proxy else 30.0
    try:
        timeout_seconds = float(timeout)
    except Exception:
        timeout_seconds = 30.0

    return ConnectorProxyRuntimeConfig(
        endpoint_url=str(endpoint_url),
        auth_mode=str(proxy.auth_mode if proxy else "none"),
        header_name=proxy.header_name if proxy else None,
        header_value=proxy.header_value if proxy else None,
        hmac_key_id=proxy.hmac_key_id if proxy else None,
        hmac_secret=proxy.hmac_secret if proxy else None,
        timeout_seconds=timeout_seconds,
    )


def build_legacy_connector_read_payload(request: ConnectorProxyReadRequest, *, connector_url: str | None = None) -> dict[str, Any]:
    size_in_bytes = _first_int(
        request.read_hint.get("sizeInBytes"),
        request.read_hint.get("size_in_bytes"),
        request.options.get("sizeInBytes"),
        request.options.get("size_in_bytes"),
    )
    read_hint_path = _first_non_empty_string(*(request.read_hint.get(key) for key in _READ_PATH_KEYS))
    options_path = _first_non_empty_string(*(request.options.get(key) for key in _READ_PATH_KEYS))
    location = _first_non_empty_string(
        request.read_hint.get("location")
        or read_hint_path,
        request.options.get("location")
        or options_path,
        request.content_source.locator,
        request.object_identity,
    )
    metainfo = _first_non_empty_string(
        request.read_hint.get("metainfo")
        or request.read_hint.get("objectIdentity")
        or request.read_hint.get("object_identity"),
        request.options.get("metainfo")
        or request.options.get("objectIdentity")
        or request.options.get("object_identity"),
        location,
        request.object_identity,
    )
    return {
        "location": str(location),
        "metainfo": str(metainfo),
        "connector_url": connector_url,
        "size_in_bytes": size_in_bytes,
        "scan_job_id": request.job_id,
    }


def _raise_structured_connector_json_error(payload: dict[str, Any], *, endpoint_url: str) -> None:
    status = str(payload.get("status") or "").lower()
    error_code = payload.get("errorCode") or payload.get("error_code") or payload.get("code")
    error_message = payload.get("errorMessage") or payload.get("error_message") or payload.get("message") or payload.get("description")
    if status not in {"error", "failed", "failure"} and not error_code:
        return
    code = str(error_code or "connector_proxy_read_failed")
    normalized = code.lower()
    if "not_found" in normalized or "notfound" in normalized or "not found" in str(error_message).lower():
        code = "object_not_found"
    elif "permission" in normalized or "forbidden" in normalized:
        code = "permission_error"
    elif "auth" in normalized or "unauthorized" in normalized:
        code = "auth_error"
    raise TerminalScanError(
        code,
        str(error_message or "connector proxy returned structured read error"),
        details={"endpointUrl": endpoint_url, "response": payload},
    )


def _build_auth_headers(config: ConnectorProxyRuntimeConfig, *, method: str, url: str, body: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    if config.auth_mode == "static_header":
        if not config.header_name or not config.header_value:
            raise TerminalScanError(
                "connector_proxy_auth_config_invalid",
                "static_header auth requires header_name and header_value",
            )
        headers[config.header_name] = config.header_value
        return headers
    if config.auth_mode == "dsx_hmac":
        if not config.hmac_key_id or not config.hmac_secret:
            raise TerminalScanError(
                "connector_proxy_auth_config_invalid",
                "dsx_hmac auth requires hmac_key_id and hmac_secret",
            )
        parsed = urlparse(url)
        path_q = parsed.path or "/"
        if parsed.query:
            path_q += f"?{parsed.query}"
        headers["Authorization"] = make_hmac_header(config.hmac_key_id, config.hmac_secret, method.upper(), path_q, body)
    return headers


def _download_stream_to_tempfile(response, *, suffix: str = "") -> tuple[str, int | None]:
    fd, temp_path = tempfile.mkstemp(prefix="dsx-ng-proxy-read-", suffix=suffix)
    os.close(fd)
    total = 0
    try:
        with open(temp_path, "wb") as out:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                out.write(chunk)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return temp_path, total


def _connector_http_read_sync(request: ConnectorProxyReadRequest, config: ConnectorProxyRuntimeConfig) -> ConnectorProxyReadResponse:
    payload = build_legacy_connector_read_payload(request, connector_url=config.endpoint_url.rsplit("/", 1)[0])
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/octet-stream, application/json",
        **_build_auth_headers(config, method="POST", url=config.endpoint_url, body=body),
    }
    req = Request(config.endpoint_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=config.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8") or "{}")
                if isinstance(payload, dict):
                    _raise_structured_connector_json_error(payload, endpoint_url=config.endpoint_url)
                raise TerminalScanError(
                    "connector_proxy_unexpected_json_response",
                    "connector proxy returned JSON instead of file content",
                    details={"endpointUrl": config.endpoint_url, "response": payload},
                )
            suffix = Path(str(payload.get("metainfo") or request.object_identity)).suffix
            temp_path, measured_length = _download_stream_to_tempfile(response, suffix=suffix)
            content_length = response.headers.get("Content-Length")
            try:
                parsed_length = int(content_length) if content_length else measured_length
            except ValueError:
                parsed_length = measured_length
            return ConnectorProxyReadResponse(
                mode="artifact_ref",
                artifact_ref=ArtifactRef(kind="local_path", locator=temp_path),
                content_length=parsed_length,
                content_type=content_type or None,
                details={
                    "source": "connector_proxy_http",
                    "endpointUrl": config.endpoint_url,
                },
            )
    except HTTPError as exc:
        raw = exc.read()
        details: dict[str, Any] = {"endpointUrl": config.endpoint_url, "statusCode": exc.code}
        if raw:
            try:
                details["response"] = json.loads(raw.decode("utf-8"))
            except Exception:
                details["responseText"] = raw.decode("utf-8", errors="replace")
        if exc.code in (429, 500, 502, 503, 504):
            raise RuntimeError(f"connector proxy transient read failure: http {exc.code}") from exc
        if exc.code == 404:
            raise TerminalScanError("object_not_found", "connector proxy reported object not found", details=details) from exc
        if exc.code == 401:
            raise TerminalScanError("auth_error", "connector proxy authentication failed", details=details) from exc
        if exc.code == 403:
            raise TerminalScanError("permission_error", "connector proxy authorization failed", details=details) from exc
        raise TerminalScanError("connector_proxy_read_failed", f"connector proxy read failed with http {exc.code}", details=details) from exc
    except URLError as exc:
        raise RuntimeError(f"connector proxy transport failure: {exc}") from exc


async def http_connector_proxy_read(request: ConnectorProxyReadRequest, config: ConnectorProxyRuntimeConfig) -> ConnectorProxyReadResponse:
    return await asyncio.to_thread(_connector_http_read_sync, request, config)


def _connector_http_stream_request(
    request: ConnectorProxyReadRequest,
    config: ConnectorProxyRuntimeConfig,
) -> tuple[Request, dict[str, Any]]:
    payload = build_legacy_connector_read_payload(request, connector_url=config.endpoint_url.rsplit("/", 1)[0])
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/octet-stream, application/json",
        **_build_auth_headers(config, method="POST", url=config.endpoint_url, body=body),
    }
    return Request(config.endpoint_url, data=body, headers=headers, method="POST"), payload


async def _connector_http_stream_chunks(
    request: ConnectorProxyReadRequest,
    config: ConnectorProxyRuntimeConfig,
    *,
    chunk_size: int = 1024 * 1024,
) -> AsyncIterable[bytes]:
    req, _payload = _connector_http_stream_request(request, config)
    response = None
    try:
        response = await asyncio.to_thread(urlopen, req, timeout=config.timeout_seconds)
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            raw = await asyncio.to_thread(response.read)
            payload = json.loads(raw.decode("utf-8") or "{}")
            if isinstance(payload, dict):
                _raise_structured_connector_json_error(payload, endpoint_url=config.endpoint_url)
            raise TerminalScanError(
                "connector_proxy_unexpected_json_response",
                "connector proxy returned JSON instead of file content",
                details={"endpointUrl": config.endpoint_url, "response": payload},
            )
        while True:
            chunk = await asyncio.to_thread(response.read, chunk_size)
            if not chunk:
                break
            yield chunk
    except HTTPError as exc:
        raw = await asyncio.to_thread(exc.read)
        details: dict[str, Any] = {"endpointUrl": config.endpoint_url, "statusCode": exc.code}
        if raw:
            try:
                details["response"] = json.loads(raw.decode("utf-8"))
            except Exception:
                details["responseText"] = raw.decode("utf-8", errors="replace")
        if exc.code in (429, 500, 502, 503, 504):
            raise RuntimeError(f"connector proxy transient read failure: http {exc.code}") from exc
        if exc.code == 404:
            raise TerminalScanError("object_not_found", "connector proxy reported object not found", details=details) from exc
        if exc.code == 401:
            raise TerminalScanError("auth_error", "connector proxy authentication failed", details=details) from exc
        if exc.code == 403:
            raise TerminalScanError("permission_error", "connector proxy authorization failed", details=details) from exc
        raise TerminalScanError("connector_proxy_read_failed", f"connector proxy read failed with http {exc.code}", details=details) from exc
    except URLError as exc:
        raise RuntimeError(f"connector proxy transport failure: {exc}") from exc
    finally:
        if response is not None:
            await asyncio.to_thread(response.close)


async def http_connector_proxy_stream(
    request: ConnectorProxyReadRequest,
    config: ConnectorProxyRuntimeConfig,
) -> ReadResult:
    _req, payload = _connector_http_stream_request(request, config)
    size_in_bytes = payload.get("size_in_bytes")
    return ReadResult(
        content_stream=_connector_http_stream_chunks(request, config),
        content_length=size_in_bytes if isinstance(size_in_bytes, int) else None,
        details={
            "reader": "connector_proxy",
            "source": "connector_proxy_http_stream",
            "endpointUrl": config.endpoint_url,
            "proxyResponse": {
                "mode": "stream",
                "details": {
                    "source": "connector_proxy_http_stream",
                    "endpointUrl": config.endpoint_url,
                },
            },
        },
    )


async def local_stub_connector_read(request: ConnectorProxyReadRequest) -> ConnectorProxyReadResponse:
    if request.content_source.mode == "none":
        raise TerminalScanError("content_source_unavailable", "proxy reader requires an available content source")
    candidates = _coalesce_local_proxy_candidates(request)
    for raw in candidates:
        path = Path(raw).expanduser()
        if path.exists() and path.is_file():
            return ConnectorProxyReadResponse(
                mode="artifact_ref",
                artifact_ref=ArtifactRef(kind="local_path", locator=str(path)),
                content_length=path.stat().st_size,
                details={"source": "connector_proxy_local_stub"},
            )
    raise TerminalScanError(
        "connector_proxy_local_content_not_found",
        "connector proxy reader could not resolve a readable local file path",
        details={
            "objectIdentity": request.object_identity,
            "contentSourceMode": request.content_source.mode,
            "contentSourceLocator": request.content_source.locator,
            "candidates": candidates,
        },
    )


class ConnectorProxyReader(Reader):
    def __init__(self, execute_proxy_read: ConnectorProxyExecutor, *, prefer_stream: bool = False) -> None:
        self.execute_proxy_read = execute_proxy_read
        self.prefer_stream = prefer_stream

    async def acquire(self, request: ScanItemRequested) -> ReadResult:
        if self.prefer_stream:
            proxy_request = ConnectorProxyReadRequest.from_scan_request(request, preferred_modes=["stream", "artifact_ref"])
            response = await self.execute_proxy_read(proxy_request)
            if isinstance(response, ReadResult):
                return response
        proxy_request = ConnectorProxyReadRequest.from_scan_request(request)
        response = await self.execute_proxy_read(proxy_request)
        if isinstance(response, ReadResult):
            return response
        if response.mode != "artifact_ref":
            raise TerminalScanError(
                "connector_proxy_response_mode_unsupported",
                f"current scan worker only supports artifact_ref proxy responses, got {response.mode}",
                details={"mode": response.mode},
            )
        artifact_ref = response.artifact_ref
        assert artifact_ref is not None
        if artifact_ref.kind != "local_path":
            raise TerminalScanError(
                "connector_proxy_artifact_kind_unsupported",
                f"current scan worker only supports local_path artifact refs, got {artifact_ref.kind}",
                details={"artifactRef": artifact_ref.model_dump(mode='json')},
            )
        path = Path(artifact_ref.locator).expanduser()
        if not path.exists() or not path.is_file():
            raise TerminalScanError(
                "connector_proxy_artifact_missing",
                "connector proxy returned a local_path artifact that is not readable",
                details={"artifactRef": artifact_ref.model_dump(mode="json")},
            )
        return ReadResult(
            local_path=path,
            content_length=response.content_length,
            cleanup_local_path=response.details.get("source") == "connector_proxy_http",
            details={
                "reader": "connector_proxy",
                "resolvedPath": str(path),
                "endpointUrl": ((response.details or {}).get("endpointUrl") if response.details else None),
                "proxyResponse": response.model_dump(mode="json"),
            },
        )


def build_connector_proxy_reader(
    request: ScanItemRequested,
    *,
    control_plane: ControlPlaneService | None,
) -> ConnectorProxyReader:
    config = resolve_connector_proxy_runtime_config(request, control_plane=control_plane)
    return ConnectorProxyReader(lambda proxy_request: http_connector_proxy_stream(proxy_request, config), prefer_stream=True)
