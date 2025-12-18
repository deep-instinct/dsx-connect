from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Optional, Set

import httpx
from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector
from connectors.framework.auth_hmac import build_outbound_auth_header
from shared.routes import service_url, API_PREFIX_V1, DSXConnectAPI
from shared.dsx_logging import dsx_logging
from shared.file_ops import relpath_matches_filter
from shared.graph.subscriptions import GraphDriveSubscriptionManager
from shared.graph.drive import build_drive_item_path, process_drive_delta_items
from shared.models.connector_models import ConnectorInstanceModel, ItemActionEnum, ScanRequestModel
from shared.models.status_responses import ItemActionStatusResponse, StatusResponse, StatusResponseEnum
from connectors.onedrive.config import config
from connectors.onedrive.onedrive_client import OneDriveClient
from connectors.onedrive.version import CONNECTOR_VERSION

from urllib.parse import quote

connector = DSXConnector(config)
client = OneDriveClient(config)
_subs_mgr: Optional[GraphDriveSubscriptionManager] = None
_subs_task: Optional[asyncio.Task] = None
_delta_lock: Optional[asyncio.Lock] = None
_delta_cursor_cache: Optional[str] = None

_STATE_NS = "od"
_DELTA_STATE_KEY = "delta:root"


def _asset_scope() -> tuple[str, str]:
    base = (config.resolved_asset_base or (config.asset or "")).strip("/")
    eff_filter = (config.filter or "").strip()
    return base, eff_filter


def _path_in_scope(path: Optional[str]) -> tuple[bool, str]:
    normalized = (path or "").strip("/")
    norm_segments = [seg for seg in normalized.split("/") if seg]
    base_path, eff_filter = _asset_scope()
    base_segments = [seg for seg in base_path.split("/") if seg]
    rel_segments = norm_segments
    if base_segments:
        if not norm_segments or len(norm_segments) < len(base_segments):
            return False, normalized
        match_idx = None
        for i in range(0, len(norm_segments) - len(base_segments) + 1):
            if norm_segments[i:i + len(base_segments)] == base_segments:
                match_idx = i
                break
        if match_idx is None:
            return False, normalized
        rel_segments = norm_segments[match_idx + len(base_segments):]
    rel = "/".join(rel_segments)
    if eff_filter and not relpath_matches_filter(rel, eff_filter):
        return False, normalized
    return True, "/".join(norm_segments)


def _normalize_drive_path(path: str) -> str:
    """
    Normalize a user-supplied OneDrive path (absolute/drive uri/relative) to a drive-relative path.
    """
    raw = (path or "").strip()
    base = config.resolved_asset_base or (config.asset or "")

    if not raw:
        return base.strip("/")

    lowered = raw.lower()
    if lowered.startswith("drives/"):
        idx = lowered.find("root:/")
        if idx != -1:
            raw = raw[idx + len("root:/"):].strip("/")
        else:
            parts = raw.split(":/", 1)
            raw = parts[1].strip("/") if len(parts) == 2 else raw
    else:
        raw = raw.strip("/")

    if not raw:
        return base.strip("/")

    base_clean = (base or "").strip("/")
    if not base_clean:
        return raw
    if raw.lower().startswith(base_clean.lower()):
        return raw
    return f"{base_clean}/{raw}".strip("/")


async def _kv_get(key: str) -> Optional[str]:
    global _delta_cursor_cache
    url = _state_url(key)
    if not url:
        return None
    headers = _signed_headers("GET", url)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as session:
            resp = await session.get(url, headers=headers or None)
        resp.raise_for_status()
        data = resp.json()
        value = data.get("value")
        if value:
            _delta_cursor_cache = value
        return value or _delta_cursor_cache
    except Exception as exc:
        dsx_logging.debug(f"state_get_failed key={key}: {exc}")
        return _delta_cursor_cache


async def _kv_put(key: str, value: str) -> None:
    global _delta_cursor_cache
    url = _state_url(key)
    if not url:
        return
    body = value.encode()
    headers = {"Content-Type": "text/plain"}
    headers.update(_signed_headers("PUT", url, body))
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as session:
            resp = await session.put(url, content=body, headers=headers)
        resp.raise_for_status()
        _delta_cursor_cache = value
    except Exception as exc:
        dsx_logging.debug(f"state_put_failed key={key}: {exc}")
        _delta_cursor_cache = value


def _state_url(key: str) -> Optional[str]:
    try:
        uuid_str = str(connector.connector_running_model.uuid)
    except Exception:
        return None
    encoded_key = quote(key, safe="")
    base = str(config.dsx_connect_url)
    return service_url(base, API_PREFIX_V1, DSXConnectAPI.CONNECTORS_PREFIX, "state", uuid_str, _STATE_NS, encoded_key)


def _signed_headers(method: str, url: str, body: bytes | None = None) -> dict[str, str]:
    header = build_outbound_auth_header(method, url, body)
    return {"Authorization": header} if header else {}


def _ensure_delta_lock() -> asyncio.Lock:
    global _delta_lock
    if _delta_lock is None:
        _delta_lock = asyncio.Lock()
    return _delta_lock


async def _initialize_delta_cursor() -> None:
    lock = _ensure_delta_lock()
    async with lock:
        if await _kv_get(_DELTA_STATE_KEY):
            return
        try:
            _, cursor = await client.delta_changes(None)
            if cursor:
                await _kv_put(_DELTA_STATE_KEY, cursor)
                dsx_logging.debug("Initialized OneDrive delta cursor from baseline delta query.")
        except Exception as exc:
            dsx_logging.debug(f"Failed to initialize delta cursor: {exc}")


async def _run_delta_sync(reason: str = "webhook", exclude_ids: Optional[Set[str]] = None) -> int:
    lock = _ensure_delta_lock()
    async with lock:
        cursor = await _kv_get(_DELTA_STATE_KEY)
        try:
            items, new_cursor = await client.delta_changes(cursor)
        except Exception as exc:
            dsx_logging.warning(f"OneDrive delta sync failed ({reason}): {exc}")
            return 0
        if new_cursor:
            await _kv_put(_DELTA_STATE_KEY, new_cursor)
        base_path, eff_filter = _asset_scope()

        async def _enqueue(item_id: str, metainfo: str, item: dict[str, Any]) -> None:
            await connector.scan_file_request(ScanRequestModel(location=item_id, metainfo=str(metainfo)))

        enqueued, _ = await process_drive_delta_items(
            items,
            exclude_ids=set(exclude_ids or ()),
            path_in_scope=_path_in_scope,
            enqueue_file=_enqueue,
            log_prefix="OneDrive",
            base_path=base_path,
            filter_text=eff_filter,
        )
        if items:
            dsx_logging.info(f"OneDrive delta sync ({reason}) items={len(items)} enqueued={enqueued}")
        return enqueued


@connector.startup
async def startup_event(base: ConnectorInstanceModel) -> ConnectorInstanceModel:
    dsx_logging.info(f"Starting up connector {base.name}")
    dsx_logging.info(f"{connector.connector_id} version: {CONNECTOR_VERSION}.")
    dsx_logging.info(f"{base.name} configuration: {config}.")

    resolved_base = (config.asset or "").strip()
    config.resolved_asset_base = resolved_base.strip("/") or None
    if config.resolved_asset_base:
        dsx_logging.info(f"Resolved OneDrive asset base: '{config.resolved_asset_base}'")
    else:
        dsx_logging.info("Resolved OneDrive asset base: entire drive")

    try:
        await client._ensure_drive()
        base.meta_info = f"OneDrive user={config.user_id}"
    except Exception as exc:
        dsx_logging.warning(f"OneDrive discovery failed on startup: {exc}")
        base.meta_info = "OneDrive discovery pending"

    if getattr(config, "webhook_enabled", False):
        try:
            global _subs_mgr, _subs_task
            await _initialize_delta_cursor()
            resource = f"/users/{config.user_id}/drive/root"
            _subs_mgr = GraphDriveSubscriptionManager(client.graph_token, resource)
            connector_base = (config.webhook_base_url or str(config.connector_url)).rstrip("/")
            route_base = config.name.strip('/') if config.name else "onedrive-connector"
            webhook_url = f"{connector_base}/{route_base}/webhook/event"
            change_types = (getattr(config, "webhook_change_types", "updated") or "updated")
            client_state = getattr(config, "webhook_client_state", None)
            expire_minutes = max(15, int(getattr(config, "webhook_expire_minutes", 60) or 60))
            refresh_seconds = max(300, int(getattr(config, "webhook_refresh_seconds", 900) or 900))

            async def _subscription_loop():
                while True:
                    try:
                        summary = await _subs_mgr.reconcile(
                            notification_url=webhook_url,
                            change_types=change_types,
                            client_state=client_state,
                            expiry_minutes=expire_minutes,
                        )
                        dsx_logging.info(f"OneDrive subscription reconcile summary: {summary}")
                    except asyncio.CancelledError:
                        break
                    except httpx.HTTPStatusError as err:
                        status = err.response.status_code if err.response is not None else "unknown"
                        detail = ""
                        try:
                            payload = err.response.json()
                            detail = payload.get("error", {}).get("message") or ""
                        except Exception:
                            try:
                                detail = err.response.text[:256]
                            except Exception:
                                detail = ""
                        hint = ""
                        if status == 400 and webhook_url.startswith("http://"):
                            hint = " (Graph requires a publicly reachable HTTPS webhook URL)"
                        dsx_logging.warning(
                            f"OneDrive subscription reconcile failed (HTTP {status}): {detail or err}. webhook_url={webhook_url}{hint}"
                        )
                    except Exception as exc:
                        dsx_logging.warning(f"OneDrive subscription reconcile failed: {exc}")
                    await asyncio.sleep(refresh_seconds)

            _subs_task = asyncio.create_task(_subscription_loop())
        except Exception as exc:
            dsx_logging.warning(f"Failed to initialize OneDrive webhook subscriptions: {exc}")

    return base


@connector.shutdown
async def shutdown_event():
    dsx_logging.info(f"Shutting down connector {connector.connector_id}")
    global _subs_task
    if _subs_task is not None:
        _subs_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _subs_task
        _subs_task = None
    try:
        await client.close()
    except Exception:
        pass


@connector.config
async def config_handler(base: ConnectorInstanceModel):
    try:
        payload = base.model_dump()
    except Exception:
        from fastapi.encoders import jsonable_encoder

        payload = jsonable_encoder(base)
    extra = {
        "asset": config.asset,
        "filter": config.filter,
        "resolved_asset_base": config.resolved_asset_base,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


@connector.full_scan
async def full_scan_handler(limit: int | None = None) -> StatusResponse:
    try:
        concurrency = max(1, int(getattr(config, "scan_concurrency", 10) or 10))
        sem = asyncio.Semaphore(concurrency)
        tasks: list[asyncio.Task] = []
        base_path = config.resolved_asset_base or ""
        eff_filter = (config.filter or "").strip()

        async def enqueue(item_id: str, metainfo: str):
            async with sem:
                await connector.scan_file_request(ScanRequestModel(location=item_id, metainfo=metainfo))

        async for item in client.iter_files_recursive(base_path):
            if item.get("folder"):
                continue
            path = (item.get("path") or item.get("name") or "").strip('/')
            in_scope, normalized = _path_in_scope(path)
            if not in_scope:
                continue
            identifier = item.get("id") or item.get("path")
            if not identifier:
                continue
            tasks.append(asyncio.create_task(enqueue(str(identifier), normalized or path)))
            if limit and len(tasks) >= limit:
                break

        if tasks:
            await asyncio.gather(*tasks)
        dsx_logging.info(f"Full scan enqueued {len(tasks)} item(s) (base='{base_path}', filter='{eff_filter}')")
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Full scan invoked", description=f"enqueued={len(tasks)}")
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(exc))


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
    try:
        base_path = config.resolved_asset_base or ""
        eff_filter = (config.filter or "").strip()
        async for item in client.iter_files_recursive(base_path):
            if item.get("folder"):
                continue
            path = (item.get("path") or item.get("name") or "").strip('/')
            in_scope, normalized = _path_in_scope(path)
            if not in_scope:
                continue
            items.append(normalized or path)
            if len(items) >= max(1, limit):
                break
    except Exception:
        pass
    return items


@connector.item_action
async def item_action_handler(scan_info: ScanRequestModel) -> ItemActionStatusResponse:
    dsx_logging.debug(f"OneDrive item_action_handler action={config.item_action} target={scan_info.location}")
    if config.item_action == ItemActionEnum.DELETE:
        try:
            target_id = await client.resolve_item_id(scan_info.location)
            await client.delete_file(target_id)
            return ItemActionStatusResponse(
                status=StatusResponseEnum.SUCCESS,
                item_action=config.item_action,
                message="File deleted",
                description=f"Deleted item {scan_info.location}"
            )
        except Exception as exc:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=config.item_action, message=str(exc))
    if config.item_action in (ItemActionEnum.MOVE, ItemActionEnum.MOVE_TAG):
        try:
            dest_raw = config.item_action_move_metainfo or ""
            dest_folder = _normalize_drive_path(dest_raw)
            await client.move_file(scan_info.location, dest_folder)
            extra = ""
            if config.item_action == ItemActionEnum.MOVE_TAG:
                extra = " Tagging skipped (not supported for OneDrive)."
            return ItemActionStatusResponse(
                status=StatusResponseEnum.SUCCESS,
                item_action=config.item_action,
                message=f"File moved.{extra}",
                description=f"Moved item {scan_info.location} to {dest_folder or 'drive root'}"
            )
        except Exception as exc:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=config.item_action, message=str(exc))
    return ItemActionStatusResponse(
        status=StatusResponseEnum.NOTHING,
        item_action=config.item_action,
        message=f"Item action {config.item_action.value} not implemented",
    )


@connector.read_file
async def read_file_handler(scan_info: ScanRequestModel):
    try:
        resp = await client.download_file(scan_info.location)

        async def agen():
            async for chunk in resp.aiter_bytes():
                yield chunk

        return StreamingResponse(agen(), media_type="application/octet-stream")
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(exc))


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    ok = await client.test_connection()
    if ok:
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="OneDrive connectivity success")
    return StatusResponse(status=StatusResponseEnum.ERROR, message="OneDrive connectivity failed")


@connector.webhook_event
async def webhook_handler(event: dict):
    dsx_logging.info("Processing OneDrive webhook event")
    payload = event if isinstance(event, dict) else {}
    notifications = payload.get("value") if isinstance(payload, dict) else None
    if isinstance(notifications, list) and notifications:
        expected_state = getattr(config, "webhook_client_state", None)
        if expected_state:
            notifications = [n for n in notifications if n.get("clientState") == expected_state]
        seen_ids: Set[str] = set()
        enqueued = 0
        for note in notifications:
            data = note.get("resourceData") if isinstance(note, dict) else None
            if not isinstance(data, dict):
                continue
            item_id = str(data.get("id") or "").strip()
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            path = data.get("name")
            if path and data.get("parentReference"):
                path = build_drive_item_path(data.get("parentReference"), path)
            in_scope, normalized = _path_in_scope(path)
            if not in_scope:
                continue
            metainfo = normalized or path or item_id
            try:
                await connector.scan_file_request(ScanRequestModel(location=item_id, metainfo=str(metainfo)))
                enqueued += 1
            except Exception as exc:
                dsx_logging.warning(f"Failed to enqueue OneDrive item {item_id}: {exc}")
        try:
            delta_added = await _run_delta_sync(reason="webhook", exclude_ids=seen_ids)
            enqueued += delta_added
        except Exception as exc:
            dsx_logging.warning(f"Delta sync after webhook failed: {exc}")
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"enqueued={enqueued}")

    ident = payload.get("id") or payload.get("item_id") or payload.get("path")
    if not ident:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="Missing item identifier in webhook event")
    try:
        if isinstance(ident, str) and ("/" in ident or ":" in ident):
            location_id = await client.resolve_item_id(ident)
            metainfo = ident
        else:
            location_id = str(ident)
            path = await client.get_item_path(location_id)
            metainfo = path or location_id
        await connector.scan_file_request(ScanRequestModel(location=location_id, metainfo=metainfo))
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed")
    except Exception as exc:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=f"Webhook error: {exc}")
