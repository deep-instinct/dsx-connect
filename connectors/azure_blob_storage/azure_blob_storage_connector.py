import asyncio
from starlette.responses import StreamingResponse

from connectors.azure_blob_storage.azure_blob_storage_client import AzureBlobClient
from connectors.framework.dsx_connector import DSXConnector
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorInstanceModel
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from connectors.azure_blob_storage.config import ConfigManager
from connectors.azure_blob_storage.version import CONNECTOR_VERSION
from shared.streaming import stream_blob
from shared.file_ops import relpath_matches_filter

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
    dsx_logging.info(f"{base.name} configuration: {config}.")
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

    async def enqueue(key: str, full_path: str):
        async with sem:
            await connector.scan_file_request(ScanRequestModel(location=key, metainfo=full_path))
            dsx_logging.debug(f"Sent scan request for {full_path}")

    page_size = getattr(config, 'list_page_size', None)
    for blob in abs_client.keys(config.asset_container, base_prefix=config.asset_prefix_root, filter_str=config.filter, page_size=page_size):
        key = blob['Key']
        # Final guard with rel path semantics
        if config.filter and not relpath_matches_filter(_rel(key), config.filter):
            continue
        full_path = f"{config.asset_container}/{key}"
        tasks.append(asyncio.create_task(enqueue(key, full_path)))
        enq_count += 1

        # Batch-gather to bound memory and provide steady backpressure
        if len(tasks) >= 200:
            await asyncio.gather(*tasks)
            tasks.clear()
        if limit and enq_count >= limit:
            break

    if tasks:
        await asyncio.gather(*tasks)
        tasks.clear()

    dsx_logging.info(
        f"Full scan enqueued {enq_count} item(s) (asset={config.asset}, filter='{config.filter or ''}', concurrency={concurrency}, page_size={page_size or 'default'})"
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
        file_stream = abs_client.get_blob(config.asset_container, scan_event_queue_info.location)
        return StreamingResponse(stream_blob(file_stream), media_type="application/octet-stream")
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
    if abs_client.test_connection(config.asset_container):
        return StatusResponse(status=StatusResponseEnum.SUCCESS,
                              message=f"Connection to {config.asset_container} successful.")
    return StatusResponse(status=StatusResponseEnum.ERROR, message=f"Connection to {config.asset_container} failed.")


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
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
