import asyncio
import os
import time
from starlette.responses import StreamingResponse, JSONResponse

from connectors.azure_blob_storage.azure_blob_storage_client import AzureBlobClient
from connectors.framework.dsx_connector import DSXConnector, _SCAN_ENQ_COUNTER
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorInstanceModel
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


def _azure_runtime_value(key: str) -> str:
    return str(os.getenv(key, "") or "")


def _azure_masked_value(key: str) -> str:
    return "**********" if _azure_runtime_value(key) else ""


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
    file_path = scan_event_queue_info.location
    if not abs_client.key_exists(config.asset_container, file_path):
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=config.item_action,
                                        message="Item action failed.",
                                        description=f"File does not exist at {config.asset_container}: {file_path}")

    if config.item_action == ItemActionEnum.DELETE:
        abs_client.delete_blob(config.asset_container, file_path)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=config.item_action,
                                        message="File deleted.",
                                        description=f"File deleted from {config.asset_container}: {file_path}")
    elif config.item_action == ItemActionEnum.MOVE:
        dest_key = f"{config.item_action_move_metainfo}/{file_path}"
        abs_client.move_blob(config.asset_container, file_path, config.asset_container, dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=config.item_action,
                                        message="File moved.",
                                        description=f"File moved from {config.asset_container}: {file_path} to {dest_key}")
    elif config.item_action == ItemActionEnum.TAG:
        abs_client.tag_blob(config.asset_container, file_path, {"Verdict": "Malicious"})
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=config.item_action,
                                        message="File tagged.",
                                        description=f"File tagged at {config.asset_container}: {file_path}")
    elif config.item_action == ItemActionEnum.MOVE_TAG:
        abs_client.tag_blob(config.asset_container, file_path, {"Verdict": "Malicious"})
        dest_key = f"{config.item_action_move_metainfo}/{file_path}"
        abs_client.move_blob(config.asset_container, file_path, config.asset_container, dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=config.item_action,
                                        message="File tagged and moved",
                                        description=f"File moved from {config.asset_container}: {file_path} to {dest_key} and tagged.")

    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING, item_action=config.item_action,
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
        file_stream, size_bytes = abs_client.get_blob_stream(
            config.asset_container,
            scan_event_queue_info.location,
            max_concurrency=getattr(config, "download_max_concurrency", 8),
        )
        prep_elapsed_ms = (time.perf_counter() - started) * 1000.0
        dsx_logging.info(
            "azure.read_file.ready job=%s blob=%s bytes=%s prep_elapsed_ms=%.1f download_max_concurrency=%s",
            getattr(scan_event_queue_info, "scan_job_id", None),
            scan_event_queue_info.location,
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

    if isinstance(payload.get("item_action"), str):
        action_raw = payload.get("item_action", "").strip().lower().replace("move_tag", "movetag")
        if action_raw:
            try:
                config.item_action = ItemActionEnum(action_raw)
                changed = True
            except Exception:
                pass

    if isinstance(payload.get("item_action_move_metainfo"), str):
        config.item_action_move_metainfo = payload.get("item_action_move_metainfo", "").strip()
        changed = True

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
