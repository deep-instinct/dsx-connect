import asyncio
import os
import time
from starlette.responses import StreamingResponse, JSONResponse

from connectors.azure_blob_storage.azure_blob_storage_client import AzureBlobClient
from connectors.framework.dsx_connector import DSXConnector, _SCAN_ENQ_COUNTER, apply_requested_action_config_update, resolve_item_action_request
from shared.models.connector_models import (
    AssetDiscoveryItem,
    AssetDiscoveryResponse,
    ScanRequestModel,
    ItemActionEnum,
    ConnectorInstanceModel,
)
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from connectors.azure_blob_storage.config import ConfigManager
from connectors.azure_blob_storage.version import CONNECTOR_VERSION
from shared.streaming import stream_blob
from shared.file_ops import relpath_matches_filter
from shared.log_sanitizer import config_for_log

# Reload config to pick up environment variables
config = ConfigManager.reload_config()
connector_id = config.name

# Derive container and base prefix from asset, supporting both "container" and "container/prefix" forms
try:
    raw_asset = (config.asset or "").strip()
    if "/" in raw_asset:
        container, prefix = raw_asset.split("/", 1)
        config.asset_container = container.strip()
        config.asset_prefix_root = prefix.strip("/")
    else:
        config.asset_container = raw_asset
        config.asset_prefix_root = ""
except Exception:
    config.asset_container = config.asset
    config.asset_prefix_root = ""

# Initialize DSX Connector instance
connector = DSXConnector(config)

abs_client = AzureBlobClient()


def _resolve_requested_item_action(scan_request: ScanRequestModel) -> tuple[ItemActionEnum, str | None, str | None, dict[str, str]]:
    resolved = resolve_item_action_request(
        scan_request,
        default_action=config.item_action,
        default_target=(config.item_action_move_metainfo or "").strip() or None,
        default_tags={"Verdict": "Malicious"} if config.item_action in (ItemActionEnum.TAG, ItemActionEnum.MOVE_TAG) else {},
    )
    return resolved.action, resolved.target, resolved.filename, dict(resolved.tags or {})


def _resolve_destination_key(source_key: str, *, target_prefix: str, target_filename: str | None) -> str:
    target_prefix = (target_prefix or "").strip("/")
    if target_filename:
        return f"{target_prefix}/{target_filename}" if target_prefix else target_filename
    return f"{target_prefix}/{source_key}" if target_prefix else source_key


def _azure_runtime_value(key: str) -> str:
    return str(os.getenv(key, "") or "")


def _azure_masked_value(key: str) -> str:
    return "**********" if _azure_runtime_value(key) else ""


def _normalize_blob_location(location: str) -> str:
    """Accept connector-relative keys and DSX-Connect container/key identities."""
    normalized = str(location or "").lstrip("/")
    container = str(config.asset_container or "").strip().strip("/")
    prefix = f"{container}/" if container else ""
    if prefix and normalized.startswith(prefix):
        return normalized[len(prefix):]
    return normalized


def _matches_asset_filter(value: str, *, mode: str | None, needle: str | None) -> bool:
    if not mode or not needle:
        return True
    normalized_value = value.lower()
    normalized_needle = needle.strip().lower()
    if not normalized_needle:
        return True
    normalized_mode = mode.strip().lower().replace("-", "_")
    if normalized_mode in {"begins_with", "starts_with", "prefix"}:
        return normalized_value.startswith(normalized_needle)
    if normalized_mode in {"ends_with", "suffix"}:
        return normalized_value.endswith(normalized_needle)
    if normalized_mode in {"contains", "substring"}:
        return normalized_needle in normalized_value
    return True


@connector.asset_discovery
async def asset_discovery_handler(
    asset_type: str = "bucket",
    source: str = "configured_asset",
    limit: int = 100,
    cursor: str | None = None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> AssetDiscoveryResponse:
    """Discover Azure Blob containers, with the configured container available by default."""
    normalized_type = (asset_type or "bucket").strip().lower()
    if ":" in normalized_type:
        normalized_type, requested_source = normalized_type.split(":", 1)
    else:
        requested_source = (source or "configured_asset").strip().lower()

    if normalized_type not in {"bucket", "buckets", "container", "containers"}:
        return AssetDiscoveryResponse(
            asset_type=normalized_type,
            source=requested_source,
            status="unsupported",
            assets=[],
            unsupported=True,
            message=f"unsupported_asset_type:{normalized_type}",
        )

    configured_selector = (config.asset or "").strip().strip("/")

    def configured_asset_item() -> AssetDiscoveryItem | None:
        if not configured_selector:
            return None
        if not _matches_asset_filter(
            configured_selector,
            mode=asset_filter_mode,
            needle=asset_filter_value,
        ):
            return None
        container_name = configured_selector.split("/", 1)[0]
        metadata = {
            "provider": "azure_blob",
            "kind": "configured_container",
            "container": container_name,
        }
        if "/" in configured_selector:
            metadata["prefix"] = configured_selector.split("/", 1)[1]
            metadata["kind"] = "configured_container_prefix"
        return AssetDiscoveryItem(
            id=configured_selector,
            display_name=configured_selector,
            selector=configured_selector,
            metadata=metadata,
        )

    if requested_source == "configured_asset":
        item = configured_asset_item()
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="configured_asset",
            status="success" if item else ("not_configured" if not configured_selector else "success"),
            assets=[item] if item else [],
            message="configured_asset_not_set" if not configured_selector else None,
        )

    try:
        containers = list(abs_client.containers())
    except Exception as exc:
        dsx_logging.warning(f"Azure container discovery failed: {exc}")
        message = str(exc)
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="inventory_enumeration",
            status="permission_denied" if "403" in message or "permission" in message.lower() else "error",
            assets=[],
            message=f"asset_discovery_failed:{message}",
            required_permission="Microsoft.Storage/storageAccounts/blobServices/containers/read",
        )

    containers = [
        name for name in containers
        if _matches_asset_filter(name, mode=asset_filter_mode, needle=asset_filter_value)
    ]
    start = max(0, int(cursor or 0)) if str(cursor or "").isdigit() else 0
    effective_limit = max(1, min(int(limit or 100), 1000))
    selected = containers[start:start + effective_limit]
    next_index = start + len(selected)
    configured_item = configured_asset_item() if requested_source in {"all", "configured_and_inventory", "configured_plus_inventory"} else None
    assets = [
        configured_item
        if configured_item is not None and name == configured_item.selector
        else AssetDiscoveryItem(
            id=name,
            display_name=name,
            selector=name,
            metadata={"provider": "azure_blob", "kind": "container", "container": name},
        )
        for name in selected
    ]
    if configured_item is not None and all(item.selector != configured_item.selector for item in assets):
        assets.insert(0, configured_item)
    return AssetDiscoveryResponse(
        asset_type="bucket",
        source=requested_source,
        status="success",
        assets=assets,
        next_cursor=str(next_index) if next_index < len(containers) else None,
    )


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
    # await abs_client.init()
    dsx_logging.info(f"{base.name} version: {CONNECTOR_VERSION}.")
    dsx_logging.info(f"{base.name} configuration: {config_for_log(config)}.")
    if not abs_client.is_configured():
        dsx_logging.error(
            f"{base.name} missing Azure credentials; connector will start but cannot read/list blobs."
        )
    dsx_logging.info(f"{base.name} startup completed.")

    prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, 'asset_prefix_root', '') else ""
    base.meta_info = f"ABS container: {config.asset_container}{prefix_disp}, filter: {config.filter or '(none)'}"
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


@connector.full_scan
async def full_scan_handler(
    limit: int | None = None,
    batch: bool = False,
    batch_size: int | None = None,
) -> StatusResponse:
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
    if not abs_client.is_configured():
        return JSONResponse(
            StatusResponse(
                status=StatusResponseEnum.ERROR,
                message="Azure credentials not configured",
                description="Set AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME/KEY",
            ).model_dump(),
            status_code=503,
        )
    # Enumerate all keys in the container (optionally optimized later) and apply rsync-like filter
    def _rel(k: str) -> str:
        bp = (config.asset_prefix_root or "").strip("/")
        if not bp:
            return k
        bp = bp + "/"
        return k[len(bp):] if k.startswith(bp) else k

    concurrency = max(1, int(getattr(config, 'scan_concurrency', 10) or 10))
    sem = asyncio.Semaphore(concurrency)
    tasks: list[asyncio.Task] = []
    enq_count = 0
    batch_errors = 0
    batch_items: list[ScanRequestModel] = []
    use_batch = bool(batch)
    effective_batch_size = 1

    if use_batch:
        caps = await connector.get_core_scan_batch_capabilities()
        if not bool(caps.get("enabled", False)):
            dsx_logging.info("Batch full scan requested but core batch mode is disabled; falling back to single-item enqueue.")
            use_batch = False
        else:
            default_size = max(1, int(caps.get("default_size", 10)))
            max_size = max(1, int(caps.get("max_size", 100)))
            requested = batch_size if isinstance(batch_size, int) and batch_size > 0 else default_size
            effective_batch_size = min(max(1, int(requested)), max_size)
            dsx_logging.info(
                f"Using ABS full-scan batch mode: effective_batch_size={effective_batch_size} "
                f"(requested={batch_size}, default={default_size}, max={max_size})"
            )

    async def _flush_batch() -> None:
        nonlocal enq_count, batch_errors, batch_items
        if not batch_items:
            return
        resp = await connector.scan_file_request_batch(batch_items, batch_size=effective_batch_size)
        if resp.status == StatusResponseEnum.SUCCESS:
            enq_count += len(batch_items)
        else:
            batch_errors += 1
            dsx_logging.warning(
                f"ABS batch enqueue failed for {len(batch_items)} item(s): "
                f"{resp.message} ({resp.description})"
            )
        batch_items = []

    async def enqueue(key: str, full_path: str):
        nonlocal enq_count, batch_errors
        async with sem:
            resp = await connector.scan_file_request(ScanRequestModel(location=key, metainfo=full_path))
            if resp.status == StatusResponseEnum.SUCCESS:
                enq_count += 1
                dsx_logging.debug(f"Sent scan request for {full_path}")
                return

            batch_errors += 1
            dsx_logging.warning(
                f"ABS single-item enqueue failed for {full_path}: "
                f"{resp.message} ({resp.description})"
            )

    page_size = getattr(config, 'list_page_size', None)
    for blob in abs_client.keys(config.asset_container, base_prefix=config.asset_prefix_root, filter_str=config.filter, page_size=page_size):
        key = blob['Key']
        # Final guard with rel path semantics
        if config.filter and not relpath_matches_filter(_rel(key), config.filter):
            continue
        full_path = f"{config.asset_container}/{key}"
        if use_batch:
            batch_items.append(ScanRequestModel(location=key, metainfo=full_path))
            if len(batch_items) >= effective_batch_size:
                await _flush_batch()
        else:
            tasks.append(asyncio.create_task(enqueue(key, full_path)))

            # Batch-gather to bound memory and provide steady backpressure
            if len(tasks) >= 200:
                await asyncio.gather(*tasks)
                tasks.clear()
        if limit and (enq_count + len(batch_items if use_batch else [])) >= limit:
            break

    if use_batch and batch_items:
        await _flush_batch()

    if tasks:
        await asyncio.gather(*tasks)
        tasks.clear()

    # Full-scan enqueue tracking uses a ContextVar in the framework. Because this
    # handler fans out with create_task(), write back the final count explicitly.
    _SCAN_ENQ_COUNTER.set(enq_count)

    dsx_logging.info(
        f"Full scan enqueued {enq_count} item(s) "
        f"(asset={config.asset}, filter='{config.filter or ''}', batch={use_batch}, batch_errors={batch_errors}, "
        f"concurrency={concurrency}, page_size={page_size or 'default'})"
    )
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message='Full scan invoked and scan requests sent.', description=f"enqueued={enq_count}")


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
    file_path = _normalize_blob_location(scan_event_queue_info.location)
    requested_action, target_prefix, target_filename, requested_tags = _resolve_requested_item_action(scan_event_queue_info)
    if not abs_client.key_exists(config.asset_container, file_path):
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                        message="Item action failed.",
                                        description=f"File does not exist at {config.asset_container}: {file_path}")

    if requested_action == ItemActionEnum.DELETE:
        abs_client.delete_blob(config.asset_container, file_path)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File deleted.",
                                        description=f"File deleted from {config.asset_container}: {file_path}")
    elif requested_action == ItemActionEnum.MOVE:
        if not target_prefix:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                            message="Item action failed.",
                                            description="Move action requires a destination path.")
        dest_key = _resolve_destination_key(file_path, target_prefix=target_prefix, target_filename=target_filename)
        abs_client.move_blob(config.asset_container, file_path, config.asset_container, dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File moved.",
                                        description=f"File moved from {config.asset_container}: {file_path} to {dest_key}")
    elif requested_action == ItemActionEnum.TAG:
        abs_client.tag_blob(config.asset_container, file_path, requested_tags)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File tagged.",
                                        description=f"File tagged at {config.asset_container}: {file_path}")
    elif requested_action == ItemActionEnum.MOVE_TAG:
        if not target_prefix:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                            message="Item action failed.",
                                            description="Move/tag action requires a destination path.")
        abs_client.tag_blob(config.asset_container, file_path, requested_tags)
        dest_key = _resolve_destination_key(file_path, target_prefix=target_prefix, target_filename=target_filename)
        abs_client.move_blob(config.asset_container, file_path, config.asset_container, dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File tagged and moved",
                                        description=f"File moved from {config.asset_container}: {file_path} to {dest_key} and tagged.")

    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING, item_action=requested_action,
                                    message="Item action did nothing or not implemented")


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
    # Implement file read (if applicable)
    try:
        if not abs_client.is_configured():
            return JSONResponse(
                StatusResponse(
                    status=StatusResponseEnum.ERROR,
                    message="Azure credentials not configured",
                    description="Set AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME/KEY",
                ).model_dump(),
                status_code=503,
            )
        started = time.perf_counter()
        file_path = _normalize_blob_location(scan_event_queue_info.location)
        file_stream, size_bytes = abs_client.get_blob_stream(
            config.asset_container,
            file_path,
            max_concurrency=getattr(config, "download_max_concurrency", 8),
        )
        prep_elapsed_ms = (time.perf_counter() - started) * 1000.0
        dsx_logging.info(
            "azure.read_file.ready job=%s blob=%s bytes=%s prep_elapsed_ms=%.1f download_max_concurrency=%s",
            getattr(scan_event_queue_info, "scan_job_id", None),
            file_path,
            size_bytes,
            prep_elapsed_ms,
            getattr(config, "download_max_concurrency", 8),
        )
        headers = {}
        if size_bytes is not None:
            headers["Content-Length"] = str(size_bytes)
        return StreamingResponse(file_stream, media_type="application/octet-stream", headers=headers)
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
    if not abs_client.is_configured():
        return JSONResponse(
            StatusResponse(
                status=StatusResponseEnum.ERROR,
                message="Azure credentials not configured",
                description="Set AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME/KEY",
            ).model_dump(),
            status_code=503,
        )
    if abs_client.test_connection(config.asset_container):
        return StatusResponse(status=StatusResponseEnum.SUCCESS,
                              message=f"Connection to {config.asset_container} successful.")
    return StatusResponse(status=StatusResponseEnum.ERROR, message=f"Connection to {config.asset_container} failed.")


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
    if not abs_client.is_configured():
        return items
    try:
        def _rel(k: str) -> str:
            bp = (config.asset_prefix_root or "").strip("/")
            if not bp:
                return k
            bp = bp + "/"
            return k[len(bp):] if k.startswith(bp) else k

        for blob in abs_client.keys(config.asset_container, base_prefix=config.asset_prefix_root, filter_str=config.filter):
            key = blob.get('Key')
            if not key:
                continue
            if config.filter and not relpath_matches_filter(_rel(key), config.filter):
                continue
            items.append(f"{config.asset_container}/{key}")
            if len(items) >= max(1, limit):
                break
    except Exception:
        pass
    return items


@connector.config
async def config_handler(base: ConnectorInstanceModel):
    """Expose runtime config for UI, including Azure credential placeholders."""
    try:
        payload = base.model_dump()
    except Exception:
        from fastapi.encoders import jsonable_encoder
        payload = jsonable_encoder(base)

    extra = {
        "asset": config.asset,
        "filter": config.filter,
        "resolved_asset_base": config.asset,
        "azure_storage_connection_string": _azure_masked_value("AZURE_STORAGE_CONNECTION_STRING"),
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


@connector.config_update
async def config_update_handler(payload: dict):
    """Update runtime-editable ABS config and persist locally when available."""
    global abs_client
    changed = False
    creds_changed = False

    if isinstance(payload.get("asset"), str):
        asset_raw = payload.get("asset", "").strip()
        if asset_raw:
            config.asset = asset_raw
            changed = True

    if isinstance(payload.get("filter"), str):
        config.filter = payload.get("filter", "")
        changed = True

    changed = (
        apply_requested_action_config_update(
            payload,
            connector_config=config,
            connector_running_model=connector.connector_running_model,
        )
        or changed
    )

    azure_updates: dict[str, str] = {}
    key_map = {
        "azure_storage_connection_string": "AZURE_STORAGE_CONNECTION_STRING",
    }
    secret_payload_keys = ("azure_storage_connection_string",)
    plain_payload_keys: tuple[str, ...] = ()

    for pkey in secret_payload_keys:
        if isinstance(payload.get(pkey), str):
            val = payload.get(pkey, "")
            # Blank means keep existing secret.
            if val:
                azure_updates[key_map[pkey]] = val
                changed = True
                creds_changed = True

    for pkey in plain_payload_keys:
        if isinstance(payload.get(pkey), str):
            val = payload.get(pkey, "").strip()
            azure_updates[key_map[pkey]] = val
            changed = True
            creds_changed = True

    if not changed:
        return {
            "error": "no_supported_fields",
            "supported": [
                "asset",
                "filter",
                "item_action",
                "item_action_move_metainfo",
                "azure_storage_connection_string",
            ],
        }

    # Keep derived parts aligned with current asset.
    try:
        raw_asset = (config.asset or "").strip()
        if "/" in raw_asset:
            container, prefix = raw_asset.split("/", 1)
            config.asset_container = container.strip()
            config.asset_prefix_root = prefix.strip("/")
        else:
            config.asset_container = raw_asset
            config.asset_prefix_root = ""
    except Exception:
        config.asset_container = config.asset
        config.asset_prefix_root = ""

    # Keep running model in sync for UI.
    try:
        connector.connector_running_model.asset = config.asset
        connector.connector_running_model.filter = config.filter
        connector.connector_running_model.item_action = config.item_action
        connector.connector_running_model.item_action_move_metainfo = config.item_action_move_metainfo
        prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, 'asset_prefix_root', '') else ""
        connector.connector_running_model.meta_info = f"ABS container: {config.asset_container}{prefix_disp}, filter: {config.filter or '(none)'}"
    except Exception:
        pass

    # Persist local runtime updates where supported.
    persisted = False
    persist_detail = "skipped"
    try:
        action_val = config.item_action.value if isinstance(config.item_action, ItemActionEnum) else str(config.item_action)
        persist_updates = {
            "DSXCONNECTOR_ASSET": str(config.asset or ""),
            "DSXCONNECTOR_FILTER": str(config.filter or ""),
            "DSXCONNECTOR_ITEM_ACTION": str(action_val or "nothing"),
            "DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO": str(config.item_action_move_metainfo or ""),
        }
        persist_updates.update(azure_updates)
        persisted, persist_detail = ConfigManager.persist_runtime_overrides(persist_updates)
    except Exception as e:
        persisted = False
        persist_detail = f"persist_error:{type(e).__name__}"

    # Keep process env in sync and rebuild client when creds changed.
    for k, v in azure_updates.items():
        os.environ[k] = v
    if creds_changed:
        try:
            abs_client = AzureBlobClient()
        except Exception:
            pass

    out = await config_handler(connector.connector_running_model)
    out["persistence"] = {
        "applied": persisted,
        "detail": persist_detail,
    }
    return out


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
    # Prefer conventional location key when available; otherwise fall back to example behavior
    location = event.get("location") or event.get("blob") or event.get("key")
    if location:
        key = str(location)
        # Filter is relative to base prefix
        bp = (config.asset_prefix_root or "").strip("/")
        bp = (bp + "/") if bp else ""
        if bp and not key.startswith(bp):
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"Ignored by base prefix: {key}")
        rel = key[len(bp):] if bp else key
        if relpath_matches_filter(rel, config.filter):
            await connector.scan_file_request(ScanRequestModel(location=key, metainfo=key))
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"Scan requested for {key}")
        else:
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"Ignored by filter: {key}")

    # Fallback: legacy example payload
    file_id = event.get("file_id", "unknown")
    await connector.scan_file_request(ScanRequestModel(location=f"custom://{file_id}", metainfo=event))
    return StatusResponse(
        status=StatusResponseEnum.SUCCESS,
        message="Webhook processed",
        description=""
    )


# @connector.config
# async def config_handler(connector_running_config: ConnectorInstanceModel):
#     # override the connector_running_config with any specific configuration details you want to add
#     return {
#         "connector_name": connector.connector_running_model.name,
#         "uuid": connector.connector_running_model.uuid,
#         "dsx_connect_url": connector.connector_running_model.url,
#         "asset": config.asset,
#         "filter": config.filter,
#         "version": CONNECTOR_VERSION
#     }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0",
                port=8599, reload=True)
