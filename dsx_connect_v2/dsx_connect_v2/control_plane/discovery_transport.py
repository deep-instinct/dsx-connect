"""Shared connector discovery transport for backend workers and interactive browsing."""
import json
from typing import Any
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request
from fastapi import HTTPException
from dsx_connect_v2.control_plane.config_models import parse_integration_runtime_config
from dsx_connect_v2.control_plane.models import IntegrationRecord, ConnectorInstanceRecord, utcnow

def _build_connector_assets_url(
    base_url: str | None,
    connector_name: str | None,
    *,
    asset_type: str,
    source: str,
    limit: int,
    cursor: str | None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> str | None:
    if not base_url:
        return None
    normalized = base_url.rstrip("/") + "/"
    path = f"{connector_name.strip('/')}/assets" if connector_name else "assets"
    endpoint = urllib_parse.urljoin(normalized, path)
    query = {"type": asset_type, "source": source, "limit": str(limit)}
    if cursor:
        query["cursor"] = cursor
    if asset_filter_mode and asset_filter_value:
        query["asset_filter_mode"] = asset_filter_mode
        query["asset_filter_value"] = asset_filter_value
    return f"{endpoint}?{urllib_parse.urlencode(query)}"


def _fetch_connector_assets(
    base_url: str | None,
    connector_name: str | None,
    *,
    asset_type: str,
    source: str,
    limit: int,
    cursor: str | None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    endpoint = _build_connector_assets_url(
        base_url,
        connector_name,
        asset_type=asset_type,
        source=source,
        limit=limit,
        cursor=cursor,
        asset_filter_mode=asset_filter_mode,
        asset_filter_value=asset_filter_value,
    )
    if endpoint is None:
        return {
            "asset_type": asset_type,
            "source": source,
            "status": "unsupported",
            "assets": [],
            "unsupported": True,
            "message": "connector_endpoint_not_configured",
        }
    request = urllib_request.Request(endpoint, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib_error.HTTPError as exc:
        raw = exc.read()
        connector_detail: dict[str, Any] | str | None = None
        if raw:
            text = raw.decode("utf-8", errors="replace")
            try:
                connector_detail = json.loads(text)
            except json.JSONDecodeError:
                connector_detail = text
        if exc.code == 404:
            return {
                "asset_type": asset_type,
                "source": source,
                "status": "unsupported",
                "assets": [],
                "unsupported": True,
                "message": "asset_discovery_not_supported",
            }
        raise HTTPException(
            status_code=502,
            detail={
                "code": "connector_asset_discovery_http_error",
                "status_code": exc.code,
                "connector_detail": connector_detail,
            },
        ) from exc
    except (urllib_error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail={"code": "connector_asset_discovery_transport_error", "message": str(exc)}) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail={"code": "connector_asset_discovery_invalid_json"}) from exc


def _connector_asset_endpoint(
    integration: IntegrationRecord,
    connector_instances: list[ConnectorInstanceRecord],
) -> tuple[str | None, str | None]:
    live_instances = [instance for instance in connector_instances if instance.expires_at > utcnow()]
    if live_instances:
        priority = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
        instance = sorted(live_instances, key=lambda item: priority.get(item.health, 99))[0]
        return instance.base_url, None
    runtime = parse_integration_runtime_config(integration.config)
    proxy = runtime.reader.proxy if runtime.reader is not None else None
    if proxy is None:
        return None, None
    return proxy.base_url, proxy.connector_name


def _default_asset_type_for_platform(platform: str | None) -> str:
    normalized = str(platform or "").strip().lower().replace("-", "_")
    if normalized == "filesystem":
        return "folder"
    return "bucket"


def _effective_asset_type(requested_type: str | None, integration: IntegrationRecord) -> str:
    normalized = str(requested_type or "").strip().lower()
    if not normalized or normalized == "auto":
        return _default_asset_type_for_platform(integration.platform)
    return normalized

