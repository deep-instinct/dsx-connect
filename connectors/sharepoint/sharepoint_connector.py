
import asyncio
import contextlib
from typing import Any, Optional, Set

import httpx
from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorInstanceModel
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from connectors.sharepoint.config import ConfigManager
from connectors.sharepoint.version import CONNECTOR_VERSION
from connectors.sharepoint.sharepoint_client import SharePointClient
from shared.graph.subscriptions import GraphDriveSubscriptionManager
from shared.graph.drive import process_drive_delta_items
from shared.file_ops import relpath_matches_filter
from connectors.framework.auth_hmac import build_outbound_auth_header
from shared.routes import service_url, API_PREFIX_V1, DSXConnectAPI
from urllib.parse import quote

# Reload config to pick up environment variables
config = ConfigManager.reload_config()
# Initialize DSX Connector instance
connector = DSXConnector(config)
sp_client = SharePointClient(config)
_subs_mgr: Optional[GraphDriveSubscriptionManager] = None
_subs_task: Optional[asyncio.Task] = None
_delta_lock: Optional[asyncio.Lock] = None
_webhook_delta_tasks: Set[asyncio.Task] = set()
_delta_cursor_cache: Optional[str] = None

_STATE_NS = "sp"
_DELTA_STATE_KEY = "delta:root"


def _asset_scope() -> tuple[str, str]:
    """Return (base_path, filter) for the monitored SharePoint scope."""
    if config.resolved_asset_base is not None:
        base = config.resolved_asset_base.strip('/')
        eff_filter = ""
    else:
        base = (config.asset or "").strip('/')
        eff_filter = (config.filter or "").strip('/')
    return base, eff_filter


def _drive_base_path() -> str:
    """Return the drive-relative base path we should enumerate under."""
    if config.resolved_asset_base is not None:
        return config.resolved_asset_base.strip('/')
    return (config.asset or "").strip('/')


def _normalize_drive_path(path: str) -> str:
    """
    Normalize a user-supplied SharePoint path (absolute URL, drive path, or relative fragment)
    to a drive-relative path suitable for Graph operations.
    """
    raw = (path or "").strip()
    base = _drive_base_path()

    if not raw:
        return base

    lowered = raw.lower()
    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            _, _, _, rel = SharePointClient.parse_sharepoint_web_url(raw)
            raw = rel or ""
        except Exception:
            raw = ""
    elif "root:/" in lowered and lowered.startswith("drives/"):
        idx = lowered.find("root:/")
        raw = raw[idx + len("root:/"):].strip("/") if idx != -1 else raw
    else:
        raw = raw.strip("/")

    if not raw:
        return base

    drive_aliases = []
    if config.sp_drive_name:
        drive_aliases.append(config.sp_drive_name)
    drive_aliases.extend(["Shared Documents", "Documents"])
    for alias in drive_aliases:
        alias_clean = alias.strip("/")
        if alias_clean and raw.lower().startswith(alias_clean.lower() + "/"):
            raw = raw[len(alias_clean) + 1:]
            break
        if alias_clean and raw.lower() == alias_clean.lower():
            raw = ""
            break

    raw = raw.strip("/")
    if not base:
        return raw
    base_clean = base.strip("/")
    if not base_clean:
        return raw
    if raw.lower().startswith(base_clean.lower()):
        return raw
    return f"{base_clean}/{raw}".strip("/")


def _path_in_scope(path: Optional[str]) -> tuple[bool, str]:
    """Check if a drive-relative path is within the configured scope."""
    normalized = (path or "").strip('/')
    norm_segments = [seg for seg in normalized.split('/') if seg]
    base_path, eff_filter = _asset_scope()
    base_segments = [seg for seg in base_path.split('/') if seg]
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


async def _derive_item_path(data: dict[str, Any], item_id: str) -> Optional[str]:
    """Best-effort resolve a drive-relative path from a Graph notification payload."""
    parent = data.get("parentReference") if isinstance(data, dict) else None
    name = data.get("name") if isinstance(data, dict) else None
    path = SharePointClient.extract_path_from_parent_reference(parent or {}, name)
    if path:
        return path
    web_url = data.get("webUrl") or data.get("weburl")
    if web_url:
        try:
            from urllib.parse import urlparse, unquote
            parsed = urlparse(str(web_url))
            path_candidate = unquote(parsed.path or "")
            if path_candidate:
                derived = SharePointClient.drive_path_from_filereF(path_candidate, config.sp_site_path)
                if derived:
                    return derived.strip('/')
        except Exception:
            pass
    try:
        resolved = await sp_client.get_item_path(item_id)
        if resolved:
            return resolved.strip('/')
    except Exception as e:
        dsx_logging.debug(f"Failed to resolve item path for id={item_id}: {e}")
    return None


def _state_url(key: str) -> str | None:
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


async def _kv_get(key: str) -> Optional[str]:
    global _delta_cursor_cache
    url = _state_url(key)
    if not url:
        return None
    headers = _signed_headers("GET", url)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as client:
            resp = await client.get(url, headers=headers or None)
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
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as client:
            resp = await client.put(url, content=body, headers=headers)
        resp.raise_for_status()
        _delta_cursor_cache = value
    except Exception as exc:
        dsx_logging.debug(f"state_put_failed key={key}: {exc}")
        _delta_cursor_cache = value


def _ensure_delta_lock() -> asyncio.Lock:
    global _delta_lock
    if _delta_lock is None:
        _delta_lock = asyncio.Lock()
    return _delta_lock


async def _initialize_delta_cursor():
    lock = _ensure_delta_lock()
    async with lock:
        existing = await _kv_get(_DELTA_STATE_KEY)
        if existing:
            return
        try:
            _, cursor = await sp_client.delta_changes(None)
            if cursor:
                await _kv_put(_DELTA_STATE_KEY, cursor)
                dsx_logging.debug("Initialized SharePoint delta cursor from baseline delta query.")
        except Exception as exc:
            dsx_logging.debug(f"Failed to initialize delta cursor: {exc}")


async def _run_delta_sync(reason: str = "webhook", exclude_ids: Optional[Set[str]] = None) -> int:
    lock = _ensure_delta_lock()
    async with lock:
        cursor = await _kv_get(_DELTA_STATE_KEY)
        try:
            items, new_cursor = await sp_client.delta_changes(cursor)
        except Exception as exc:
            dsx_logging.warning(f"SharePoint delta sync failed ({reason}): {exc}")
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
            log_prefix="SharePoint",
            base_path=base_path,
            filter_text=eff_filter,
        )
        if items:
            dsx_logging.info(f"SharePoint delta sync ({reason}) items={len(items)} enqueued={enqueued}")
        return enqueued


def _schedule_delta_sync(reason: str, exclude_ids: Optional[Set[str]] = None) -> None:
    """
    Schedule a background delta sync so webhook handlers can ACK immediately.
    """
    task = asyncio.create_task(_run_delta_sync(reason=reason, exclude_ids=set(exclude_ids or set())))
    _webhook_delta_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _webhook_delta_tasks.discard(t)
        try:
            result = t.result()
            dsx_logging.debug(f"Background delta sync ({reason}) completed enqueued={result}")
        except Exception as exc:
            dsx_logging.warning(f"Background delta sync ({reason}) failed: {exc}")

    task.add_done_callback(_on_done)


@connector.startup
async def startup_event(base: ConnectorInstanceModel) -> ConnectorInstanceModel:
    """
    Startup handler for the DSX Connector.

    This function is invoked by dsx-connector during the startup phase of the connector.
    It should be used to initialize any required resources, such as setting up connections,
    starting background tasks, or performing initial configuration checks.

    Returns:
        ConnectorInstanceModel: the base dsx-connector will have populated this model, modify as needed and return
    """
    dsx_logging.info(f"Starting up connector {base.name}")
    dsx_logging.info(f"{connector.connector_id} version: {CONNECTOR_VERSION}.")
    dsx_logging.info(f"{base.name} configuration: {config}.")
    dsx_logging.info(f"{base.name} startup completed.")

    # Derive SharePoint connection details from ASSET (URL) once at startup, and
    # pre-compute the resolved asset base path inside the drive applying FILTER.
    # This avoids re-parsing in handlers and keeps locations stable.
    try:
        friendly_site: Optional[str] = None
        friendly_drive: Optional[str] = None
        friendly_rel: Optional[str] = None
        asset = (config.asset or "").strip()
        if asset.startswith("http://") or asset.startswith("https://"):
            try:
                host, site, drive_name, rel_path = SharePointClient.parse_sharepoint_web_url(asset)
                # If env didn't set host/site, adopt from ASSET. Otherwise keep env but warn on mismatch.
                if not config.sp_hostname:
                    config.sp_hostname = host
                elif config.sp_hostname != host:
                    dsx_logging.warning(f"ASSET host '{host}' differs from configured '{config.sp_hostname}'; using configured.")

                if not config.sp_site_path:
                    config.sp_site_path = site
                elif config.sp_site_path != site:
                    dsx_logging.warning(f"ASSET site '{site}' differs from configured '{config.sp_site_path}'; using configured.")

                # Drive name if provided; otherwise let client pick default
                if drive_name and not config.sp_drive_name:
                    config.sp_drive_name = drive_name

                base_path = rel_path or ""
                # Prefer showing the original ASSET URL in the UI card 'Asset:' line.
                # The UI uses asset_display_name > resolved_asset_base > asset. We use a friendly path.
                friendly_site = site
                friendly_drive = drive_name or "Documents"
                friendly_rel = rel_path or ""
                try:
                    base.asset_display_name = asset
                except Exception:
                    pass
            except Exception as e:
                dsx_logging.warning(f"Failed to parse DSXCONNECTOR_ASSET URL; using raw asset/filter: {e}")
                base_path = asset
        else:
            base_path = asset

        # Apply filter as subpath
        flt = (config.filter or "").strip("/")
        if flt:
            base_path = f"{base_path.strip('/')}/{flt}" if base_path else flt
            if friendly_rel is not None:
                friendly_rel = f"{friendly_rel.strip('/')}/{flt}".strip('/')
            elif friendly_drive is not None:
                friendly_rel = flt
        config.resolved_asset_base = base_path.strip('/')
        if config.resolved_asset_base:
            dsx_logging.info(f"Resolved SharePoint asset base: '{config.resolved_asset_base}'")
        else:
            dsx_logging.info("Resolved SharePoint asset base: root of drive")
        # Update asset_display_name with friendly components if we parsed them.
        try:
            if friendly_site:
                display_parts = [friendly_site]
                if friendly_drive:
                    display_parts.append(friendly_drive)
                if friendly_rel:
                    display_parts.append(friendly_rel)
                base.asset_display_name = "/".join([part for part in display_parts if part])
        except Exception:
            pass
    except Exception as e:
        dsx_logging.warning(f"Failed to derive resolved asset base: {e}")

    # Attempt to resolve site/drive on startup so readiness can pass
    try:
        await sp_client.site_drive_ids()
        base.meta_info = f"SharePoint site={config.sp_site_path}, drive={config.sp_drive_name or 'default'}"
    except Exception as e:
        dsx_logging.warning(f"SharePoint discovery failed on startup: {e}")
        base.meta_info = "SharePoint discovery pending"

    # Kick off Graph subscription reconciliation if enabled
    if getattr(config, "sp_webhook_enabled", False):
        try:
            global _subs_mgr, _subs_task
            await _initialize_delta_cursor()
            site_id, drive_id = await sp_client.site_drive_ids()
            resource = f"/sites/{site_id}/drives/{drive_id}/root"
            _subs_mgr = GraphDriveSubscriptionManager(sp_client.graph_token, resource)
            connector_base = (config.webhook_base_url or str(config.connector_url)).rstrip("/")
            route_base = config.name.strip('/') if config.name else "sharepoint-connector"
            webhook_url = f"{connector_base}/{route_base}/webhook/event"
            change_types = (getattr(config, "sp_webhook_change_types", "updated") or "updated")
            client_state = getattr(config, "sp_webhook_client_state", None)
            expire_minutes = max(15, int(getattr(config, "sp_webhook_expire_minutes", 60) or 60))
            refresh_seconds = max(300, int(getattr(config, "sp_webhook_refresh_seconds", 900) or 900))

            async def _subscription_loop():
                while True:
                    try:
                        summary = await _subs_mgr.reconcile(
                            notification_url=webhook_url,
                            change_types=change_types,
                            client_state=client_state,
                            expiry_minutes=expire_minutes,
                        )
                        dsx_logging.info(f"SharePoint subscription reconcile summary: {summary}")
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
                            f"SharePoint subscription reconcile failed (HTTP {status}): {detail or err}. webhook_url={webhook_url}{hint}"
                        )
                    except Exception as exc:
                        dsx_logging.warning(f"SharePoint subscription reconcile failed: {exc}")
                    await asyncio.sleep(refresh_seconds)

            _subs_task = asyncio.create_task(_subscription_loop())
        except Exception as exc:
            dsx_logging.warning(f"Failed to initialize SharePoint webhook subscriptions: {exc}")
    return base


@connector.shutdown
async def shutdown_event():
    """
    Shutdown handler for the DSX Connector.

    This function is called by dsx-connect when the connector is shutting down.
    Use this handler to clean up resources such as closing connections or stopping background tasks.

    Returns:
        None
    """
    dsx_logging.info(f"Shutting down connector {connector.connector_id}")
    global _subs_task
    if _subs_task is not None:
        _subs_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _subs_task
        _subs_task = None
    if _webhook_delta_tasks:
        for task in list(_webhook_delta_tasks):
            task.cancel()
        for task in list(_webhook_delta_tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await task
            _webhook_delta_tasks.discard(task)
    try:
        await sp_client.aclose()
    except Exception:
        pass


@connector.config
async def config_handler(base: ConnectorInstanceModel):
    """Expose connector runtime config for the UI, including resolved asset base."""
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
    """
    Full Scan handler for the DSX Connector.

    This function is invoked by DSX Connect when a full scan of the connector's repository is requested.
    If your connector supports scanning all files (e.g., a filesystem or cloud storage connector), implement
    the logic to enumerate all files and trigger individual scan requests, using the base
    connector scan_file_request function.

    Example:
        iterate through files in a repository, and send a scan_file_request to dsx-connect for each file

        ```python
        async for file_path in file_ops.get_filepaths_async('F:/FileShare', True):
            await connector.scan_file_request(ScanRequestModel(location=str(file_path), metainfo=file_path.name))
        ```

        You can choose whatever location makes sense, as long as this connector can use it
        in read_file to read the file, whereever it is located.  The flow works like this:
        full_scan is invoked by dsx_connect, as it wants a full scan on whatever respository this
        connector is assigned to.  This connector in turn, enumerates through all files and
        sends a ScanEventQueueModel for each to dsx-connect, and more specifically, a queue
        of scan requests that dsx-connect will process.  dsx-connect then processes each
        queue item, calling read_file for each file that needs to be read.

    Args:
        scan_event_queue_info (ScanRequestModel): Contains metadata and location information necessary
            to perform a full scan.

    Returns:
        SimpleResponse: A response indicating success if the full scan is initiated, or an error if the
            functionality is not supported. (For connectors without full scan support, return an error response.)
    """
    # Iterate files and enqueue scan requests
    try:
        base_path = _drive_base_path()
        _, eff_filter = _asset_scope()
        concurrency = max(1, int(getattr(config, 'scan_concurrency', 10) or 10))
        sem = asyncio.Semaphore(concurrency)
        tasks: list[asyncio.Task] = []

        async def enqueue(item_id: str, metainfo: str):
            async with sem:
                dsx_logging.debug(f"Enqueuing scan request for item {item_id}")
                await connector.scan_file_request(ScanRequestModel(location=item_id, metainfo=metainfo))

        # Choose enumeration strategy: delta (fast) or recursive (baseline)
        provider_mode = (getattr(config, 'sp_provider_mode', 'graph') or 'graph').lower()
        use_delta = bool(getattr(config, 'sp_use_delta_for_scan', False))
        async def iter_items():
            if provider_mode == 'spo_rest' and getattr(config, 'sp_list_id', None):
                # REST mode: enumerate list rows
                async for row in sp_client.iter_list_items_rest(config.sp_list_id, row_limit=int(getattr(config, 'sp_rest_row_limit', 5000) or 5000)):
                    # Prefer FileRef when present (document libraries), else build a simple path from Title/ID
                    file_ref = row.get("FileRef") or row.get("FileRef.urlencoded") or row.get("ServerUrl")
                    if file_ref:
                        drive_path = SharePointClient.drive_path_from_filereF(str(file_ref), config.sp_site_path)
                        yield {"id": drive_path, "path": drive_path}
                    else:
                        name = row.get("FileLeafRef") or row.get("Title") or f"item-{row.get('ID')}"
                        yield {"id": str(row.get("ID")), "path": str(name)}
            else:
                # Graph modes
                if use_delta:
                    async for it in sp_client.iter_files_delta():
                        yield it
                else:
                    async for it in sp_client.iter_files_recursive(base_path):
                        yield it

        async for item in iter_items():
            if item.get("folder"):
                continue
            # Determine a repository-relative path to apply filters
            item_path = (item.get("path") or item.get("name") or "").strip('/')
            if base_path:
                # For delta-based enumeration, filter by base_path prefix
                if not item_path.startswith(base_path.rstrip('/') + "/") and item_path != base_path:
                    continue
                # Strip base_path so eff_filter applies on the remainder
                rel_for_filter = item_path[len(base_path):].lstrip('/')
            else:
                rel_for_filter = item_path
            if eff_filter and not relpath_matches_filter(rel_for_filter, eff_filter):
                continue
            # In REST mode we use drive path as identifier to avoid a per-item resolve round-trip.
            identifier = item.get("id") if provider_mode != 'spo_rest' else item_path
            metainfo = item_path
            tasks.append(asyncio.create_task(enqueue(identifier, metainfo)))
            if limit and len(tasks) >= limit:
                break

        if tasks:
            await asyncio.gather(*tasks)
        count = len(tasks)
        mode_desc = 'spo_rest' if provider_mode == 'spo_rest' else ('delta' if use_delta else 'recursive')
        asset_base_log = config.resolved_asset_base if config.resolved_asset_base is not None else (config.asset or "")
        dsx_logging.info(
            f"Full scan enqueued {count} item(s) (asset_base='{asset_base_log}', filter='{config.filter or ''}', mode={mode_desc})"
        )
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message='Full scan invoked and scan requests sent.', description=f"enqueued={count}")
    except Exception as e:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(e))


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
    try:
        base_path = _drive_base_path()
        _, eff_filter = _asset_scope()
        async for item in sp_client.iter_files_recursive(base_path):
            if item.get("folder"):
                continue
            path = (item.get("path") or item.get("name") or "").strip('/')
            if base_path:
                if not path.startswith(base_path.rstrip('/') + "/") and path != base_path:
                    continue
                rel_for_filter = path[len(base_path):].lstrip('/')
            else:
                rel_for_filter = path
            if eff_filter and not relpath_matches_filter(rel_for_filter, eff_filter):
                continue
            items.append(path or item.get("id", ""))
            if len(items) >= max(1, limit):
                break
    except Exception:
        pass
    return items


@connector.item_action
async def item_action_handler(scan_event_queue_info: ScanRequestModel) -> ItemActionStatusResponse:
    """
    Item Action handler for the DSX Connector.

    This function is called by DSX Connect when a file is determined to be malicious
    (or some other condition which DSX Connect thinks of a need to take action on a
    file)
    The connector should implement the appropriate remediation action here (e.g., delete, move, or tag the file)
    based on the provided quarantine configuration.

    Args:
        scan_event_queue_info (ScanRequestModel): Contains the location and metadata of the item that requires action.

    Returns:
        SimpleResponse: A response indicating that the remediation action was performed successfully,
            or an error if the action is not implemented.
    """
    dsx_logging.debug(f"SharePoint item_action_handler action={config.item_action} target={scan_event_queue_info.location}")
    # DELETE
    if config.item_action == ItemActionEnum.DELETE:
        try:
            target_id = await sp_client.resolve_item_id(scan_event_queue_info.location)
            await sp_client.delete_file(target_id)
            return ItemActionStatusResponse(
                status=StatusResponseEnum.SUCCESS,
                item_action=config.item_action,
                message="File deleted.",
                description=f"Deleted item id {scan_event_queue_info.location}"
            )
        except Exception as e:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=config.item_action,
                message=str(e)
            )
    # MOVE
    if config.item_action in (ItemActionEnum.MOVE, ItemActionEnum.MOVE_TAG):
        try:
            dest_raw = config.item_action_move_metainfo or ""
            dest_folder = _normalize_drive_path(dest_raw)
            dest_folder = dest_folder.strip("/") if dest_folder else ""
            await sp_client.move_file(scan_event_queue_info.location, dest_folder)
            extra = ""
            if config.item_action == ItemActionEnum.MOVE_TAG:
                extra = " Tagging skipped (not supported for SharePoint)."
            return ItemActionStatusResponse(
                status=StatusResponseEnum.SUCCESS,
                item_action=config.item_action,
                message=f"File moved.{extra}",
                description=f"Moved item {scan_event_queue_info.location} to {dest_folder or 'drive root'}"
            )
        except Exception as e:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=config.item_action,
                message=str(e)
            )
    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING,
                                    item_action=config.item_action,
                                    message=f"Item action {config.item_action.value} not supported for SharePoint")


@connector.read_file
async def read_file_handler(scan_event_queue_info: ScanRequestModel) -> StatusResponse | StreamingResponse:
    """
    Read File handler for the DSX Connector.

    This function is invoked by DSX Connect when it needs to retrieve the content of a file.
    The connector should implement logic here to read the file from its repository (e.g., file system,
    S3 bucket, etc.) and return its contents wrapped in a FileContentResponse.

    Example:
    ```python
        @connector.read_file
        def read_file_handler(scan_event_queue_info: ScanEventQueueModel):
            file_path = pathlib.Path(scan_event_queue_info.location)

            # Check if the file exists
            if not os.path.isfile(file_path):
                return StatusResponse(status=StatusResponseEnum.ERROR,
                                    message=f"File {file_path} not found")

                # Read the file content
            try:
                file_like = file_path.open("rb")  # Open file in binary mode
                return StreamingResponse(file_like, media_type="application/octet-stream")  # Stream file
            except Exception as e:
                return StatusResponse(status=StatusResponseEnum.ERROR,
                                      message=f"Failed to read file: {str(e)}")
    ```

    Args:
        scan_event_queue_info (ScanRequestModel): Contains the location and metadata needed to locate and read the file.

    Returns:
        FileContentResponse or SimpleResponse: A successful FileContentResponse containing the file's content,
            or a SimpleResponse with an error message if file reading is not supported.
    """
    try:
        resp = await sp_client.download_file(scan_event_queue_info.location)

        async def agen():
            async for chunk in resp.aiter_bytes():
                yield chunk

        return StreamingResponse(agen(), media_type="application/octet-stream")
    except Exception as e:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=str(e))


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    """
    Repository connectivity check handler.

    This handler verifies that the configured repository location exists and this DSX Connector can connect to it.

    Returns:
        bool: True if the repository connectivity OK, False otherwise.
    """
    ok = await sp_client.test_connection()
    if ok:
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="SharePoint connectivity success")
    return StatusResponse(status=StatusResponseEnum.ERROR, message="SharePoint connectivity failed")

@connector.webhook_event
async def webhook_handler(event: dict):
    """
    Webhook Event handler for the DSX Connector.

    This function is invoked by external systems (e.g., third-party file repositories or notification services)
    when a new file event occurs. The connector should extract the necessary file details from the event payload
    (for example, a file ID or name) and trigger a scan request via DSX Connect using the connector.scan_file_request method.

    Args:
        event (dict): The JSON payload sent by the external system containing file event details.

    Returns:
        SimpleResponse: A response indicating that the webhook was processed and the file scan request has been initiated,
            or an error if processing fails.
    """
    dsx_logging.info("Processing webhook event")
    payload = event if isinstance(event, dict) else {}
    notifications = payload.get("value") if isinstance(payload, dict) else None
    if isinstance(notifications, list) and notifications:
        expected_state = getattr(config, "sp_webhook_client_state", None)
        if expected_state:
            notifications = [n for n in notifications if n.get("clientState") == expected_state]
        enqueued = 0
        delta_needed = False
        seen_ids: Set[str] = set()
        for note in notifications:
            data = note.get("resourceData") if isinstance(note, dict) else None
            if not isinstance(data, dict):
                delta_needed = True
                continue
            if data.get("deleted"):
                continue
            if data.get("folder") and not data.get("file"):
                # Folder-only notification; rely on delta if needed to pick up nested files.
                delta_needed = True
                continue
            item_id = str(data.get("id") or "").strip()
            if not item_id:
                resource = note.get("resource") or ""
                item_id = SharePointClient.item_id_from_resource(resource) or ""
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            path = await _derive_item_path(data, item_id)
            in_scope, normalized = _path_in_scope(path)
            if not in_scope:
                dsx_logging.debug(f"Ignoring notification for item {item_id}: outside scope (path='{path}')")
                continue
            metainfo = normalized or data.get("name") or item_id
            try:
                await connector.scan_file_request(ScanRequestModel(location=item_id, metainfo=str(metainfo)))
                enqueued += 1
            except Exception as exc:
                dsx_logging.warning(f"Failed to enqueue scan for SharePoint item {item_id}: {exc}")
                delta_needed = True
            if not path:
                delta_needed = True
        if notifications and (delta_needed or enqueued == 0):
            _schedule_delta_sync(reason="webhook", exclude_ids=seen_ids)
        return StatusResponse(
            status=StatusResponseEnum.SUCCESS,
            message="Webhook processed",
            description=f"enqueued={enqueued}; delta sync {'scheduled' if delta_needed or enqueued == 0 else 'skipped'}",
        )

    ident = payload.get("id") or payload.get("item_id") or payload.get("path") or payload.get("webUrl")
    if not ident:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="Missing item identifier in webhook event")

    try:
        # Legacy/manual payload handling: accept id, path, or full URL as before.
        if isinstance(ident, str) and (ident.startswith("http://") or ident.startswith("https://")):
            try:
                _, _, _, rel = SharePointClient.parse_sharepoint_web_url(ident)
                metainfo: Any = rel or ident
            except Exception:
                metainfo = ident
            location_id = await sp_client.resolve_item_id(str(metainfo))
        elif isinstance(ident, str) and ("/" in ident or ":" in ident):
            metainfo = ident
            location_id = await sp_client.resolve_item_id(ident)
        else:
            location_id = str(ident)
            try:
                path = await sp_client.get_item_path(location_id)
                metainfo = path or payload.get("name") or location_id
            except Exception:
                metainfo = payload.get("name") or location_id

        await connector.scan_file_request(ScanRequestModel(location=location_id, metainfo=metainfo))
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed")
    except Exception as e:
        return StatusResponse(status=StatusResponseEnum.ERROR, message=f"Webhook error: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0",
                port=8620, reload=True)
