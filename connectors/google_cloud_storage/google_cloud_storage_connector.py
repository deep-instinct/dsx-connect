import json
import os
import threading

from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector
from connectors.google_cloud_storage.gcs_client import GCSClient
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorInstanceModel, ConnectorStatusEnum
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from connectors.google_cloud_storage.config import ConfigManager
from connectors.google_cloud_storage.version import CONNECTOR_VERSION
from shared.async_ops import run_async
from shared.file_ops import relpath_matches_filter
from shared.log_sanitizer import config_for_log
from shared.streaming import stream_blob

# Reload config to pick up environment variables
config = ConfigManager.reload_config()

DEFAULT_PUBSUB_EVENTS: set[str] = {"OBJECT_FINALIZE", "OBJECT_METADATA_UPDATE"}

# Derive bucket and base prefix from asset, supporting both "bucket" and "bucket/prefix" forms
try:
    raw_asset = (config.asset or "").strip()
    if "/" in raw_asset:
        bucket, prefix = raw_asset.split("/", 1)
        config.asset_bucket = bucket.strip()
        config.asset_prefix_root = prefix.strip("/")
    else:
        config.asset_bucket = raw_asset
        config.asset_prefix_root = ""
except Exception:
    config.asset_bucket = config.asset
    config.asset_prefix_root = ""

connector = DSXConnector(config)

gcs_client = GCSClient()

_monitor_thread: threading.Thread | None = None
_monitor_stop = threading.Event()


def _should_monitor() -> bool:
    if not getattr(config, "monitor", False):
        return False
    if not config.pubsub_project_id or not config.pubsub_subscription:
        dsx_logging.warning(
            "GCS monitor enabled but PUB/SUB project or subscription is missing; monitoring disabled."
        )
        return False
    return True


def _start_pubsub_monitor():
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return

    try:
        from google.cloud import pubsub_v1  # local import to keep optional dependency optional
    except Exception as exc:
        dsx_logging.error(f"Failed to import google.cloud.pubsub_v1: {exc}")
        return

    project = config.pubsub_project_id.strip()
    subscription_name = config.pubsub_subscription.strip()
    if not project or not subscription_name:
        dsx_logging.warning("Pub/Sub project or subscription not configured; skipping monitor thread.")
        return

    client_options = {}
    endpoint = getattr(config, "pubsub_endpoint", "") or ""
    if endpoint:
        client_options["api_endpoint"] = endpoint

    subscriber = pubsub_v1.SubscriberClient(client_options=client_options or None)
    if subscription_name.startswith("projects/"):
        subscription_path = subscription_name
    else:
        subscription_path = subscriber.subscription_path(project, subscription_name)

    accepted_types = set(DEFAULT_PUBSUB_EVENTS)
    bucket_prefix = (config.asset_prefix_root or "").strip("/")
    if bucket_prefix:
        bucket_prefix = bucket_prefix + "/"

    def handle_message(message):
        try:
            attrs = message.attributes or {}
            raw_data = message.data.decode("utf-8") if message.data else ""
            payload = {}
            if raw_data:
                try:
                    payload = json.loads(raw_data)
                except Exception:
                    payload = {}

            bucket = attrs.get("bucketId") or attrs.get("bucket_id") or payload.get("bucket")
            obj = attrs.get("objectId") or attrs.get("object_id") or payload.get("name")
            event_type = attrs.get("eventType") or attrs.get("event_type") or payload.get("eventType") or ""
            event_type = str(event_type).upper()

            if bucket and bucket != config.asset_bucket:
                message.ack()
                return

            if not obj:
                message.ack()
                return

            if bucket_prefix and not obj.startswith(bucket_prefix):
                message.ack()
                return

            if event_type and accepted_types and event_type not in accepted_types:
                message.ack()
                return

            full_path = f"{config.asset_bucket}/{obj}" if config.asset_bucket else obj

            async def enqueue_scan():
                await connector.scan_file_request(
                    ScanRequestModel(location=obj, metainfo=full_path)
                )

            run_async(enqueue_scan())
            dsx_logging.info(f"GCS Pub/Sub enqueue for {full_path} ({event_type or 'unknown event'})")
            message.ack()
        except Exception as exc:
            dsx_logging.error(f"Failed to process Pub/Sub message: {exc}")
            try:
                message.nack()
            except Exception:
                pass

    def worker():
        dsx_logging.info(
            f"Starting GCS Pub/Sub monitor on {subscription_path} (events: {', '.join(sorted(accepted_types))})"
        )
        streaming_future = subscriber.subscribe(subscription_path, callback=handle_message)
        try:
            while not _monitor_stop.wait(5):
                continue
        except Exception as exc:
            dsx_logging.error(f"Pub/Sub subscriber error: {exc}")
        finally:
            streaming_future.cancel()
            subscriber.close()
            dsx_logging.info("GCS Pub/Sub monitor stopped")

    _monitor_stop.clear()
    _monitor_thread = threading.Thread(target=worker, name="gcs-pubsub-monitor", daemon=True)
    _monitor_thread.start()


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

    dsx_logging.info(f"{base.name} version: {CONNECTOR_VERSION}.")
    dsx_logging.info(f"{base.name} configuration: {config_for_log(config)}.")
    dsx_logging.info(f"{base.name} startup completed.")

    base.status = ConnectorStatusEnum.READY
    prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, 'asset_prefix_root', '') else ""
    base.meta_info = f"GCS Bucket: {config.asset_bucket}{prefix_disp}, filter: {config.filter or '(none)'}"

    if _should_monitor():
        _start_pubsub_monitor()

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
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_stop.set()
        _monitor_thread.join(timeout=10)
        if _monitor_thread.is_alive():
            dsx_logging.warning("Pub/Sub monitor thread did not exit cleanly")
    _monitor_thread = None


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
    def _rel(k: str) -> str:
        bp = (config.asset_prefix_root or "").strip("/")
        if not bp:
            return k
        bp = bp + "/"
        return k[len(bp):] if k.startswith(bp) else k

    requests: list[ScanRequestModel] = []
    count = 0
    for blob in gcs_client.keys(config.asset_bucket, base_prefix=config.asset_prefix_root, filter_str=config.filter):
        key = blob['Key']
        if config.filter and not relpath_matches_filter(_rel(key), config.filter):
            continue
        full_path = f"{config.asset_bucket}/{key}"
        requests.append(ScanRequestModel(location=key, metainfo=full_path))
        if limit and len(requests) >= limit:
            break

    if batch:
        effective_batch_size = max(1, int(batch_size or 100))
        dsx_logging.info(
            f"Using GCS full-scan batch mode: effective_batch_size={effective_batch_size}"
        )
        for idx in range(0, len(requests), effective_batch_size):
            chunk = requests[idx:idx + effective_batch_size]
            if not chunk:
                continue
            result = await connector.scan_file_request_batch(chunk)
            if result.status == StatusResponseEnum.SUCCESS:
                count += len(chunk)
                dsx_logging.debug(
                    f"Sent GCS scan batch for {len(chunk)} item(s), total_enqueued={count}"
                )
            else:
                dsx_logging.warning(
                    f"GCS scan batch enqueue failed for {len(chunk)} item(s): {result}"
                )
    else:
        for request in requests:
            result = await connector.scan_file_request(request)
            if result.status == StatusResponseEnum.SUCCESS:
                dsx_logging.debug(f"Sent scan request for {request.metainfo}")
                count += 1
            else:
                dsx_logging.warning(f"GCS scan enqueue failed for {request.metainfo}: {result}")

    dsx_logging.info(
        f"Full scan enqueued {count} item(s) (asset={config.asset}, filter='{config.filter or ''}')"
    )
    return StatusResponse(
        status=StatusResponseEnum.SUCCESS,
        message='Full scan invoked and scan requests sent.',
        description=f"enqueued={count}"
    )


@connector.preview
async def preview_provider(limit: int) -> list[str]:
    items: list[str] = []
    try:
        for blob in gcs_client.keys(config.asset_bucket, base_prefix=config.asset_prefix_root, filter_str=config.filter):
            key = blob.get('Key')
            if not key:
                continue
            if config.filter and not relpath_matches_filter(_rel(key), config.filter):
                continue
            items.append(f"{config.asset_bucket}/{key}")
            if len(items) >= max(1, limit):
                break
    except Exception:
        pass
    return items


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
        "resolved_asset_base": config.asset,
        "monitor": bool(getattr(config, "monitor", False)),
        "google_application_credentials": str(getattr(config, "google_application_credentials", "") or ""),
        "pubsub_project_id": str(getattr(config, "pubsub_project_id", "") or ""),
        "pubsub_subscription": str(getattr(config, "pubsub_subscription", "") or ""),
        "pubsub_endpoint": str(getattr(config, "pubsub_endpoint", "") or ""),
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload

@connector.item_action
async def item_action_handler(scan_event_queue_info: ScanRequestModel) -> StatusResponse:
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
    if not gcs_client.key_exists(config.asset_bucket, file_path):
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=config.item_action, message="Item action failed.", description=f"File does not exist at {config.asset}: {file_path}")

    if config.item_action == ItemActionEnum.DELETE:
            gcs_client.delete_object(config.asset_bucket, file_path)
            return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=ItemActionEnum.DELETE, message="File deleted.", description=f"File deleted from {config.asset}: {file_path}")
    elif config.item_action == ItemActionEnum.MOVE:
        dest_key = f"{config.item_action_move_metainfo}/{file_path}"
        gcs_client.move_object(config.asset_bucket, file_path, config.asset_bucket, dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=ItemActionEnum.MOVE, message="File moved.", description=f"File moved from {config.asset}: {file_path} to {dest_key}")
    elif config.item_action == ItemActionEnum.TAG:
        gcs_client.tag_object(config.asset_bucket, file_path, {"Verdict": "Malicious"})
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=ItemActionEnum.TAG, message="File tagged.", description=f"File tagged at {config.asset}: {file_path}")
    return ItemActionStatusResponse(status=StatusResponseEnum.NOTHING, item_action=config.item_action, message="Item action did nothing or not implemented")


@connector.config_update
async def config_update_handler(payload: dict):
    global gcs_client
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

    gcs_updates: dict[str, str] = {}
    if payload.get("monitor") is not None:
        if isinstance(payload.get("monitor"), str):
            config.monitor = payload.get("monitor", "").strip().lower() == "true"
            changed = True
        elif isinstance(payload.get("monitor"), bool):
            config.monitor = bool(payload.get("monitor"))
            changed = True

    if isinstance(payload.get("google_application_credentials"), str):
        val = payload.get("google_application_credentials", "").strip()
        config.google_application_credentials = val or None
        gcs_updates["GOOGLE_APPLICATION_CREDENTIALS"] = val
        changed = True
        creds_changed = True

    for key in ("pubsub_project_id", "pubsub_subscription", "pubsub_endpoint"):
        if isinstance(payload.get(key), str):
            setattr(config, key, payload.get(key, "").strip())
            changed = True

    if not changed:
        return {
            "error": "no_supported_fields",
            "supported": [
                "asset",
                "filter",
                "item_action",
                "item_action_move_metainfo",
                "monitor",
                "google_application_credentials",
                "pubsub_project_id",
                "pubsub_subscription",
                "pubsub_endpoint",
            ],
        }

    try:
        raw_asset = (config.asset or "").strip()
        if "/" in raw_asset:
            bucket, prefix = raw_asset.split("/", 1)
            config.asset_bucket = bucket.strip()
            config.asset_prefix_root = prefix.strip("/")
        else:
            config.asset_bucket = raw_asset
            config.asset_prefix_root = ""
    except Exception:
        config.asset_bucket = config.asset
        config.asset_prefix_root = ""

    try:
        connector.connector_running_model.asset = config.asset
        connector.connector_running_model.filter = config.filter
        connector.connector_running_model.item_action = config.item_action
        connector.connector_running_model.item_action_move_metainfo = config.item_action_move_metainfo
        prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, "asset_prefix_root", "") else ""
        connector.connector_running_model.meta_info = f"GCS Bucket: {config.asset_bucket}{prefix_disp}, filter: {config.filter or '(none)'}"
    except Exception:
        pass

    try:
        ConfigManager._config = config
    except Exception:
        pass

    persisted = False
    persist_detail = "skipped"
    try:
        action_val = config.item_action.value if isinstance(config.item_action, ItemActionEnum) else str(config.item_action)
        persist_updates = {
            "DSXCONNECTOR_ASSET": str(config.asset or ""),
            "DSXCONNECTOR_FILTER": str(config.filter or ""),
            "DSXCONNECTOR_ITEM_ACTION": str(action_val or "nothing"),
            "DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO": str(config.item_action_move_metainfo or ""),
            "DSXCONNECTOR_MONITOR": "true" if bool(getattr(config, "monitor", False)) else "false",
            "DSXCONNECTOR_PUBSUB_PROJECT_ID": str(config.pubsub_project_id or ""),
            "DSXCONNECTOR_PUBSUB_SUBSCRIPTION": str(config.pubsub_subscription or ""),
            "DSXCONNECTOR_PUBSUB_ENDPOINT": str(config.pubsub_endpoint or ""),
        }
        persist_updates.update(gcs_updates)
        persisted, persist_detail = ConfigManager.persist_runtime_overrides(persist_updates)
    except Exception as e:
        persisted = False
        persist_detail = f"persist_error:{type(e).__name__}"

    if "GOOGLE_APPLICATION_CREDENTIALS" in gcs_updates:
        cred_path = gcs_updates["GOOGLE_APPLICATION_CREDENTIALS"]
        if cred_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        else:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    if creds_changed:
        try:
            gcs_client = GCSClient()
        except Exception:
            pass

    out = await config_handler(connector.connector_running_model)
    out["persistence"] = {
        "applied": persisted,
        "detail": persist_detail,
    }
    return out



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
        file_stream = gcs_client.get_object(config.asset_bucket, scan_event_queue_info.location)
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
    if gcs_client.test_gcs_connection(bucket=config.asset_bucket):
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message=f"Connection to {config.asset} successful.")
    return StatusResponse(status=StatusResponseEnum.ERROR, message=f"Connection to {config.asset} failed.")


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
    # Prefer conventional GCS notification schema when present
    key = event.get("name") or event.get("object") or event.get("location")
    if key:
        k = str(key)
        if config.filter and not relpath_matches_filter(k, config.filter):
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"Ignored by filter: {k}")
        await connector.scan_file_request(ScanRequestModel(location=k, metainfo=k))
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description=f"Scan requested for {k}")

    # Fallback: example payload with file_id
    file_id = event.get("file_id", "unknown")
    await connector.scan_file_request(ScanRequestModel(location=f"custom://{file_id}", metainfo=event))
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Webhook processed", description="")



if __name__ == "__main__":
    import uvicorn

    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0",
                port=8595, reload=False)
