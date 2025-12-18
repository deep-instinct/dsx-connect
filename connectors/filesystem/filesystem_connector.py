import errno
import os
import pathlib
import shutil
from uuid import uuid4

import uvicorn

from starlette.responses import StreamingResponse

from shared.file_ops import get_filepaths_async
from connectors.framework.dsx_connector import DSXConnector
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorInstanceModel, \
    ConnectorStatusEnum
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
# Optional dependency: filesystem monitor (dev/local convenience). Fallback to no-op stubs if unavailable.
try:
    from filesystem_monitor import FilesystemMonitor, FilesystemMonitorCallback
except Exception:
    class FilesystemMonitorCallback:  # type: ignore
        def __init__(self):
            pass
        def file_modified_callback(self, file_path: pathlib.Path):
            pass

    class FilesystemMonitor:  # type: ignore
        def __init__(self, folder: pathlib.Path, filter: str, callback: FilesystemMonitorCallback,
                     force_polling: bool = False, poll_interval_ms: int = 1000):
            self.folder = folder
            self.filter = filter
            self.callback = callback
            self.force_polling = force_polling
            self.poll_interval_ms = poll_interval_ms
        def start(self):
            dsx_logging.info("FilesystemMonitor not installed; monitor disabled.")
from shared.async_ops import run_async
from connectors.filesystem.config import ConfigManager
from connectors.filesystem.version import CONNECTOR_VERSION

# Reload config to pick up environment variables
config = ConfigManager.reload_config()
connector = DSXConnector(config)


def _normalize_path(p: str | pathlib.Path) -> pathlib.Path:
    if isinstance(p, pathlib.Path):
        path = p
    else:
        path = pathlib.Path(os.path.expandvars(p))
    path = path.expanduser()
    try:
        return path.resolve()
    except Exception:
        return path


# given that this could potentially be a lengthy file iteration, make the iteration asynchronous...
# TODO possibly should allow startup of FAstAPI to complete, and schedule full scans in the background
async def start_monitor():
    """
    Create a filesystem monitor and capture the file information to send to the webhook/event.
    """
    if config.monitor:
        class MonitorCallback(FilesystemMonitorCallback):
            def __init__(self):
                super().__init__()

            def file_modified_callback(self, file_path: pathlib.Path):
                dsx_logging.debug(f'Sending scan request for {file_path}')
                run_async(
                    connector.webhook_handler(ScanRequestModel(location=str(file_path), metainfo=file_path.name)))

        # Determine quarantine path relative to asset if a relative path is supplied
        raw_quarantine = config.item_action_move_metainfo or ""
        quarantine_path = pathlib.Path(os.path.expandvars(raw_quarantine)).expanduser()
        if not quarantine_path.is_absolute():
            base_asset = _normalize_path(config.asset)
            quarantine_path = (base_asset / quarantine_path).resolve()

        monitor_callback = MonitorCallback()

        # Expand '~' and env vars, resolve to absolute path, and validate directory exists before starting watch
        watch_path = pathlib.Path(os.path.expandvars(config.asset)).expanduser()
        try:
            # resolve to absolute path (directory is expected to exist)
            watch_path = watch_path.resolve()
        except Exception:
            # if resolve fails, continue with expanded path and rely on exists()/is_dir()
            pass
        if not watch_path.exists() or not watch_path.is_dir():
            dsx_logging.error(
                f"Filesystem monitor path does not exist or is not a directory: {watch_path}. "
                f"Update DSXCONNECTOR_ASSET or create the folder."
            )
            return

        ignore_paths: list[pathlib.Path] = []
        if quarantine_path.exists():
            ignore_paths.append(quarantine_path)

        connector.filesystem_monitor = FilesystemMonitor(
            folder=watch_path,
            filter=config.filter,
            callback=monitor_callback,
            force_polling=bool(getattr(config, 'monitor_force_polling', False)),
            poll_interval_ms=int(getattr(config, 'monitor_poll_interval_ms', 1000)),
            ignore_paths=ignore_paths,
        )
        connector.filesystem_monitor.start()
        dsx_logging.info(f"Monitor set on {watch_path} for new or modified files with filter: {config.filter}")
    else:
        dsx_logging.info(f"Monitor set to false, {config.asset} will not be monitored for new or modified files")


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

    dsx_logging.info(f"{base.name} version: {CONNECTOR_VERSION}.")
    dsx_logging.info(f"{base.name} configuration: {config}.")
    dsx_logging.info(f"{base.name} startup completed.")

    if not config.monitor:
        dsx_logging.info(f"Monitor set to false, {config.asset} will not be monitored for new or modified files")
    else:
        await start_monitor()

    base.status = ConnectorStatusEnum.READY
    base.meta_info = f"Filesystem location: {config.asset}"
    return base


@connector.shutdown
async def shutdown_event():
    dsx_logging.info(f"{config.name} shutdown completed.")


@connector.full_scan
async def full_scan_handler(limit: int | None = None) -> StatusResponse:
    dsx_logging.debug(
        f"Scanning files at: {config.asset}, filter='{config.filter}')"
    )
    count = 0
    async for file_path in get_filepaths_async(
            pathlib.Path(config.asset),
            config.filter):
        status_response = await connector.scan_file_request(
            ScanRequestModel(location=str(file_path), metainfo=file_path.name))
        dsx_logging.debug(f'Sent scan request for {file_path}, result: {status_response}')
        count += 1
        if limit and count >= limit:
            break
    dsx_logging.info(f"Full scan enqueued {count} item(s) (asset={config.asset}, filter='{config.filter or ''}')")
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message='Full scan invoked and scan requests sent.', description=f"enqueued={count}")


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
    try:
        base = pathlib.Path(config.asset)
        i = 0
        async for file_path in get_filepaths_async(base, config.filter):
            items.append(str(file_path))
            i += 1
            if i >= max(1, limit):
                break
    except Exception:
        pass
    return items


@connector.webhook_event
async def webhook_handler(event: dict | ScanRequestModel) -> StatusResponse:
    """
    Handle inbound webhook-style events for the filesystem connector.

    Accepts either a dict payload with at least a 'location' field, or a
    ScanRequestModel (used internally by the monitor callback).
    """
    try:
        if isinstance(event, ScanRequestModel):
            req = event
        else:
            location = event.get("location") or event.get("path") or event.get("file_path")
            if not location:
                return StatusResponse(
                    status=StatusResponseEnum.ERROR,
                    message="Invalid filesystem event format",
                    description="Missing 'location' (or 'path'/'file_path') in event payload",
                )
            metainfo = event.get("metainfo") or pathlib.Path(str(location)).name
            req = ScanRequestModel(location=str(location), metainfo=str(metainfo))

        dsx_logging.info(f"Received filesystem event for {req.location}")
        response = await connector.scan_file_request(req)
        return StatusResponse(
            status=response.status,
            message="Filesystem webhook processed",
            description=f"Scan request sent for {req.location}",
        )
    except Exception as e:
        dsx_logging.error(f"Unexpected error in webhook handler: {e}", exc_info=True)
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Internal error during webhook handling",
            description=str(e),
        )


@connector.item_action
async def item_action_handler(scan_event_queue_info: ScanRequestModel) -> StatusResponse:
    file_path = scan_event_queue_info.location
    path_obj = _normalize_path(file_path)

    if not path_obj.is_file():
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=config.item_action,
                                        message="Item action failed.",
                                        description=f"File does not exist at {file_path}")

    if config.item_action == ItemActionEnum.DELETE:
        dsx_logging.debug(f'Item action {ItemActionEnum.DELETE} on {file_path} invoked.')
        path_obj.unlink()
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS,
                                        item_action=config.item_action,
                                        message='File deleted.',
                                        description=f"File deleted from {file_path}")
    elif config.item_action == ItemActionEnum.MOVE:
        dsx_logging.debug(f'Item action {ItemActionEnum.MOVE} on {file_path} invoked.')

        raw_target = config.item_action_move_metainfo or ""
        dest_root = pathlib.Path(os.path.expandvars(raw_target)).expanduser()
        if not dest_root.is_absolute():
            dest_root = (_normalize_path(config.asset) / dest_root).resolve()
        else:
            dest_root = dest_root.resolve()
        dest_root.mkdir(parents=True, exist_ok=True)

        def _unique_destination(base_dir: pathlib.Path, name: str) -> pathlib.Path:
            candidate = base_dir / name
            if not candidate.exists():
                return candidate
            stem = candidate.stem
            suffix = candidate.suffix
            while True:
                alt = base_dir / f"{stem}-{uuid4().hex[:6]}{suffix}"
                if not alt.exists():
                    return alt

        destination = _unique_destination(dest_root, path_obj.name)

        try:
            path_obj.rename(destination)
        except OSError as exc:
            if exc.errno in {errno.EXDEV, errno.EACCES, errno.EPERM, errno.EEXIST}:
                try:
                    shutil.move(str(path_obj), str(destination))
                except Exception as inner_exc:
                    error_msg = f'Failed to move file {file_path} into {destination}: {inner_exc}'
                    dsx_logging.error(error_msg)
                    return ItemActionStatusResponse(
                        status=StatusResponseEnum.ERROR,
                        message=error_msg,
                        item_action=config.item_action,
                    )
            else:
                error_msg = f'Failed to move file {file_path}: {exc}'
                dsx_logging.error(error_msg)
                return ItemActionStatusResponse(
                    status=StatusResponseEnum.ERROR,
                    message=error_msg,
                    item_action=config.item_action,
                )

        return ItemActionStatusResponse(
            status=StatusResponseEnum.SUCCESS,
            item_action=config.item_action,
            message="File moved",
            description=f'Item action {config.item_action} was invoked. File {file_path} successfully moved to {destination}.'
        )

    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING, item_action=config.item_action,
                                    message="Item action did nothing or not implemented")


def stream_file(file_like, chunk_size: int = 1024 * 1024):
    while True:
        chunk = file_like.read(chunk_size)
        if not chunk:
            break
        yield chunk


@connector.read_file
async def read_file_handler(scan_request_info: ScanRequestModel) -> StreamingResponse | StatusResponse:
    file_path = _normalize_path(scan_request_info.location)

    # Check if the file exists
    if not file_path.is_file():
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message=f"File {file_path} not found")

    # Read the file content
    try:
        file_like = file_path.open("rb")  # Open file in binary mode
        return StreamingResponse(stream_file(file_like), media_type="application/octet-stream")  # Stream file
    except Exception as e:
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message=f"Failed to read file: {str(e)}")


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    """
    Repository connectivity check handler.

    This handler verifies that the configured repository location exists and this DSX Connector can connect to it.

    Returns:
        bool: True if the repository connectivity OK, False otherwise.
    """
    # Expand '~' and env vars and resolve the path for a reliable existence check
    try:
        test_path = pathlib.Path(os.path.expandvars(config.asset)).expanduser()
        try:
            test_path = test_path.resolve()
        except Exception:
            pass
    except Exception:
        test_path = pathlib.Path(str(config.asset))

    if test_path.exists():
        return StatusResponse(
            status=StatusResponseEnum.SUCCESS,
            message=f"{test_path} connectivity success.")
    else:
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message=f"Repo check failed for {test_path}",
            description="")


# @connector.config
# async def config_handler(connector_running_config: ConnectorInstanceModel):
#     # override the connector_running_config with any specific configuration details you want to add
#     if config.asset_display_name:
#         dsx_logging.info(f"Setting asset to asset display name {config.asset_display_name}")
#         connector_running_config.asset = config.asset_display_name
#     return connector_running_config


# Main entry point to start the FastAPI app
if __name__ == "__main__":
    # Uvicorn will serve the FastAPI app and keep it running
    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0", port=8590, reload=False, workers=1)
