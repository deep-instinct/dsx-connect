from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterable, List, Set

from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector
from connectors.salesforce.config import ConfigManager, SalesforceConnectorConfig
from connectors.salesforce.salesforce_client import SalesforceClient
from connectors.salesforce.version import CONNECTOR_VERSION
from shared.dsx_logging import dsx_logging
from shared.models.connector_models import ConnectorInstanceModel, ItemActionEnum, ScanRequestModel
from shared.models.status_responses import ItemActionStatusResponse, StatusResponse, StatusResponseEnum

# Reload config to pick up environment variables and initialise client.
config: SalesforceConnectorConfig = ConfigManager.reload_config()
connector = DSXConnector(config)
sf_client = SalesforceClient(config)


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

    # Sanity check credentials on boot if possible
    try:
        if await sf_client.repo_health():
            dsx_logging.info("Salesforce connectivity check succeeded during startup.")
    except Exception as exc:
        dsx_logging.warning("Salesforce startup health check failed: %s", exc)

    # modify ConnectorModel as needed and return
    # base.meta_info = ...
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
    try:
        await sf_client.close()
    except Exception:
        pass


@connector.full_scan
async def full_scan_handler() -> StatusResponse:
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
    limit = config.sf_max_records if config.sf_max_records > 0 else None
    queued = 0
    try:
        async for record in _iter_salesforce_records(limit):
            if not _include_record(record):
                continue
            location = record.get("Id")
            if not location:
                continue
            metainfo = record.get("Title") or record.get("PathOnClient") or record.get("ContentDocumentId") or location
            scan_req = ScanRequestModel(
                location=location,
                metainfo=metainfo,
            )
            await connector.scan_file_request(scan_req)
            queued += 1
        return StatusResponse(
            status=StatusResponseEnum.SUCCESS,
            message=f"Queued {queued} Salesforce ContentVersion rows.",
            description="",
        )
    except Exception as exc:
        dsx_logging.exception("Full scan failed")
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Full scan failed",
            description=str(exc),
        )


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    """
    Optional preview provider: return up to N sample item identifiers for the UI.
    Replace the sample stub with a cheap repository listing (no side-effects).
    """
    # Example stub; replace with a repository-specific peek (e.g., list objects/prefix)
    samples: list[str] = []
    max_rows = max(1, min(int(limit or 5), 25))
    try:
        async for record in _iter_salesforce_records(limit=max_rows):
            title = record.get("Title") or record.get("ContentDocumentId") or record.get("Id")
            if title:
                samples.append(str(title))
            if len(samples) >= max_rows:
                break
    except Exception as exc:
        dsx_logging.warning("Preview provider failed: %s", exc)
    return samples


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
    return ItemActionStatusResponse(
        status=StatusResponseEnum.NOTHING,
        item_action=ItemActionEnum.NOT_IMPLEMENTED,
        message=f"Item action not implemented.")


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
    version_id = (scan_event_queue_info.location or "").strip()
    if not version_id:
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Missing ContentVersion Id",
            description="location must contain a ContentVersion Id",
        )

    async def iterator() -> AsyncIterator[bytes]:
        async for chunk in sf_client.stream_content_version(version_id):
            yield chunk

    filename = scan_event_queue_info.metainfo or f"{version_id}.bin"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(iterator(), media_type="application/octet-stream", headers=headers)


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    """
    Repository connectivity check handler.

    This handler verifies that the configured repository location exists and this DSX Connector can connect to it.

    Returns:
        bool: True if the repository connectivity OK, False otherwise.
    """
    try:
        ok = await sf_client.repo_health()
        if ok:
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Salesforce connection verified.", description="")
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Salesforce limits check failed.",
            description="Salesforce REST API returned non-200 during repo check.",
        )
    except Exception as exc:
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Salesforce repo check failed",
            description=str(exc),
        )

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
        StatusResponse: summary of queued scans.
    """
    version_ids = _extract_version_ids(event)
    if not version_ids:
        dsx_logging.info("Salesforce webhook received payload with no version IDs: %s", event)
        return StatusResponse(
            status=StatusResponseEnum.NOTHING,
            message="Webhook payload did not include ContentVersion identifiers.",
            description="",
        )

    queued = 0
    for version_id in version_ids:
        scan_req = ScanRequestModel(
            location=version_id,
            metainfo=f"Salesforce ContentVersion {version_id}",
        )
        await connector.scan_file_request(scan_req)
        queued += 1
    return StatusResponse(
        status=StatusResponseEnum.SUCCESS,
        message=f"Queued {queued} ContentVersion items from webhook.",
        description="",
    )


def _extension_filter() -> Set[str]:
    entries = (config.filter or "").split(",")
    return {entry.strip().lower().lstrip(".") for entry in entries if entry.strip()}


def _include_record(record: Dict[str, any]) -> bool:
    ext_filter = _extension_filter()
    if not ext_filter:
        return True
    ext = (record.get("FileExtension") or "").strip().lower()
    return ext in ext_filter


async def _iter_salesforce_records(limit: int | None) -> AsyncIterator[Dict[str, any]]:
    async for record in sf_client.iter_content_versions(limit=limit):
        yield record


def _extract_version_ids(payload: any) -> List[str]:
    ids: Set[str] = set()

    def _walk(value: any):
        if isinstance(value, dict):
            for key in ("ContentVersionId", "VersionId", "VersionIds", "contentVersionId", "contentVersionIds", "Id", "id"):
                entry = value.get(key)
                if isinstance(entry, str) and entry:
                    ids.add(entry)
                elif isinstance(entry, Iterable) and not isinstance(entry, (str, bytes)):
                    for item in entry:
                        if isinstance(item, str) and item:
                            ids.add(item)
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)
    return sorted(ids)
