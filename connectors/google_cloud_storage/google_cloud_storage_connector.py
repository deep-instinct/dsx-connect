import json
import os
import threading

from starlette.responses import StreamingResponse

from connectors.framework.dsx_connector import DSXConnector, apply_requested_action_config_update, resolve_item_action_request
from connectors.google_cloud_storage.gcs_client import GCSClient
from shared.models.connector_models import AssetDiscoveryItem, AssetDiscoveryResponse, ObjectListingItem, ObjectListingResponse, ScanRequestModel, ItemActionEnum, ConnectorInstanceModel, ConnectorStatusEnum
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


def _normalize_asset_inventory_scope(scope: str | None) -> str:
    raw = str(scope or "").strip().strip("/")
    if not raw:
        return ""
    aliases = {
        "project": "projects",
        "folder": "folders",
        "organization": "organizations",
        "org": "organizations",
    }
    if ":" in raw and "/" not in raw:
        kind, value = raw.split(":", 1)
        kind = aliases.get(kind.strip().lower(), kind.strip().lower())
        value = value.strip()
        return f"{kind}/{value}" if kind and value else ""
    parts = raw.split("/", 1)
    if len(parts) != 2:
        return raw
    kind, value = parts
    return f"{aliases.get(kind.strip().lower(), kind.strip().lower())}/{value.strip()}"


def _bucket_name_from_cloud_asset(asset) -> str:
    resource = getattr(asset, "resource", None)
    data = getattr(resource, "data", None) or {}
    try:
        bucket_name = data.get("name")
    except AttributeError:
        bucket_name = None
    if bucket_name:
        return str(bucket_name)
    name = str(getattr(asset, "name", "") or "")
    if "/buckets/" in name:
        return name.rsplit("/buckets/", 1)[-1]
    return name.rsplit("/", 1)[-1]


def _cloud_asset_metadata(asset) -> dict:
    resource = getattr(asset, "resource", None)
    data = getattr(resource, "data", None) or {}

    def _get(key: str):
        try:
            return data.get(key)
        except AttributeError:
            return None

    metadata = {
        "provider": "gcs",
        "discovery_source": "cloud_asset_inventory",
        "asset_type": str(getattr(asset, "asset_type", "") or getattr(asset, "assetType", "") or "storage.googleapis.com/Bucket"),
        "asset_name": str(getattr(asset, "name", "") or ""),
    }
    for key in ("location", "storageClass", "projectNumber", "timeCreated", "updated"):
        value = _get(key)
        if value is not None:
            metadata[key] = str(value)
    return metadata


def _list_cloud_asset_inventory_buckets(
    *,
    scope: str,
    limit: int,
    cursor: str | None = None,
) -> tuple[list[AssetDiscoveryItem], str | None]:
    parent = _normalize_asset_inventory_scope(scope)
    if not parent:
        raise RuntimeError("cloud_asset_inventory_scope_not_configured")
    try:
        from google.cloud import asset_v1
    except Exception as exc:
        raise RuntimeError("google-cloud-asset is required for Cloud Asset Inventory discovery") from exc

    client = asset_v1.AssetServiceClient()
    request = {
        "parent": parent,
        "asset_types": ["storage.googleapis.com/Bucket"],
        "content_type": asset_v1.ContentType.RESOURCE,
        "page_size": max(1, min(int(limit or 100), 1000)),
    }
    if cursor:
        request["page_token"] = cursor

    response = client.list_assets(request=request)
    page = None
    page_source = getattr(response, "pages", None)
    if page_source is not None:
        try:
            page = next(iter(page_source))
        except StopIteration:
            page = []
    else:
        page = response

    assets: list[AssetDiscoveryItem] = []
    for asset in page:
        bucket = _bucket_name_from_cloud_asset(asset)
        if not bucket:
            continue
        metadata = _cloud_asset_metadata(asset)
        metadata["bucket"] = bucket
        metadata["asset_inventory_scope"] = parent
        assets.append(
            AssetDiscoveryItem(
                id=bucket,
                display_name=bucket,
                selector=bucket,
                metadata=metadata,
            )
        )
    raw_response = getattr(response, "_response", None)
    next_cursor = (
        getattr(page, "next_page_token", None)
        or getattr(response, "next_page_token", None)
        or getattr(raw_response, "next_page_token", None)
    )
    return assets, (str(next_cursor) if next_cursor else None)


def _resolve_requested_item_action(scan_request: ScanRequestModel) -> tuple[ItemActionEnum, str | None, dict[str, str]]:
    resolved = resolve_item_action_request(
        scan_request,
        default_action=config.item_action,
        default_target=(config.item_action_move_metainfo or "").strip() or None,
        default_tags={"Verdict": "Malicious"} if config.item_action in (ItemActionEnum.TAG, ItemActionEnum.MOVE_TAG) else {},
    )
    return resolved.action, resolved.target, dict(resolved.tags or {})


def _quarantine_target_config(scan_request: ScanRequestModel) -> tuple[bool, str]:
    requested = scan_request.requested_action
    details = requested.details if requested and requested.details else {}
    quarantine_target = details.get("quarantine_target") or {}
    preserve_relative = bool(quarantine_target.get("preserve_relative_path", True))
    resolved_filename = (
        ((requested.destination or {}).get("filename")) if requested and requested.destination else None
    ) or details.get("resolved_filename") or scan_request.location.rsplit("/", 1)[-1]
    return preserve_relative, str(resolved_filename)


def _resolve_quarantine_object_key(
    *,
    source_key: str,
    target_prefix: str,
    preserve_relative_path: bool,
    resolved_filename: str,
) -> str:
    target_prefix = target_prefix.rstrip("/")
    source_parent = source_key.rsplit("/", 1)[0] if "/" in source_key else ""
    if preserve_relative_path and source_parent:
        return f"{target_prefix}/{source_parent}/{resolved_filename}"
    return f"{target_prefix}/{resolved_filename}"


def _relative_to_configured_prefix(key: str) -> str:
    bp = (config.asset_prefix_root or "").strip("/")
    if not bp:
        return key
    bp = bp + "/"
    return key[len(bp):] if key.startswith(bp) else key


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
    batch_max_items = max(1, int(getattr(config, "pubsub_batch_max_items", 100) or 100))
    batch_max_seconds = max(0.1, float(getattr(config, "pubsub_batch_max_seconds", 2.0) or 2.0))
    pending: list[tuple[ScanRequestModel, object, str, str]] = []
    pending_lock = threading.Lock()
    pending_ready = threading.Event()

    def _ack_message(message) -> None:
        try:
            message.ack()
        except Exception:
            pass

    def _nack_message(message) -> None:
        try:
            message.nack()
        except Exception:
            pass

    def flush_pending(reason: str) -> None:
        with pending_lock:
            batch = list(pending)
            pending.clear()
            pending_ready.clear()
        if not batch:
            return

        requests = [entry[0] for entry in batch]

        async def enqueue_scan_batch():
            return await connector.scan_file_request_batch(requests, batch_size=len(requests))

        try:
            result = run_async(enqueue_scan_batch())
            result_status = getattr(result.status, "value", result.status)
            if result_status == StatusResponseEnum.SUCCESS.value:
                for _request, message, _full_path, _event_type in batch:
                    _ack_message(message)
                sample = ", ".join(entry[2] for entry in batch[:3])
                if len(batch) > 3:
                    sample = f"{sample}, ..."
                dsx_logging.info(
                    f"GCS Pub/Sub batch enqueue for {len(batch)} object(s) "
                    f"(reason={reason}, sample={sample})"
                )
                return

            if result_status == StatusResponseEnum.NOTHING.value:
                for _request, message, _full_path, _event_type in batch:
                    _ack_message(message)
                sample = ", ".join(entry[2] for entry in batch[:3])
                if len(batch) > 3:
                    sample = f"{sample}, ..."
                dsx_logging.debug(
                    f"GCS Pub/Sub batch skipped {len(batch)} object(s) "
                    f"(reason={reason}, description={result.description}, sample={sample})"
                )
                return

            for _request, message, _full_path, _event_type in batch:
                _nack_message(message)
            dsx_logging.warning(
                f"GCS Pub/Sub batch enqueue failed for {len(batch)} object(s): {result}"
            )
        except Exception as exc:
            for _request, message, _full_path, _event_type in batch:
                _nack_message(message)
            dsx_logging.error(f"Failed to enqueue GCS Pub/Sub scan batch: {exc}")

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
            request = ScanRequestModel(
                location=obj,
                metainfo=full_path,
                scan_source="connector_monitor",
            )
            with pending_lock:
                pending.append((request, message, full_path, event_type or "unknown event"))
                should_flush = len(pending) >= batch_max_items
            if should_flush:
                pending_ready.set()
        except Exception as exc:
            dsx_logging.error(f"Failed to process Pub/Sub message: {exc}")
            _nack_message(message)

    def worker():
        dsx_logging.info(
            f"Starting GCS Pub/Sub monitor on {subscription_path} "
            f"(events: {', '.join(sorted(accepted_types))}; "
            f"batch_max_items={batch_max_items}; batch_max_seconds={batch_max_seconds})"
        )
        streaming_future = subscriber.subscribe(subscription_path, callback=handle_message)
        try:
            while not _monitor_stop.is_set():
                signaled = pending_ready.wait(timeout=batch_max_seconds)
                flush_pending("max_items" if signaled else "timer")
        except Exception as exc:
            dsx_logging.error(f"Pub/Sub subscriber error: {exc}")
        finally:
            streaming_future.cancel()
            flush_pending("shutdown")
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
    requests: list[ScanRequestModel] = []
    count = 0
    for blob in gcs_client.keys(config.asset_bucket, base_prefix=config.asset_prefix_root, filter_str=config.filter):
        key = blob['Key']
        if config.filter and not relpath_matches_filter(_relative_to_configured_prefix(key), config.filter):
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
            if config.filter and not relpath_matches_filter(_relative_to_configured_prefix(key), config.filter):
                continue
            items.append(f"{config.asset_bucket}/{key}")
            if len(items) >= max(1, limit):
                break
    except Exception:
        pass
    return items


@connector.object_listing
async def object_listing_handler(scope: str = "", limit: int = 1000, cursor: str | None = None) -> ObjectListingResponse:
    requested_scope = (scope or config.asset or config.asset_bucket or "").strip().strip("/")
    configured_bucket = (config.asset_bucket or "").strip()
    if not configured_bucket:
        return ObjectListingResponse(
            scope=requested_scope,
            status="not_configured",
            objects=[],
            message="asset_bucket_not_configured",
        )

    bucket = configured_bucket
    requested_prefix = (config.asset_prefix_root or "").strip("/")
    if requested_scope:
        if requested_scope == configured_bucket:
            requested_prefix = (config.asset_prefix_root or "").strip("/")
        elif requested_scope.startswith(configured_bucket + "/"):
            requested_prefix = requested_scope[len(configured_bucket) + 1:].strip("/")
        else:
            return ObjectListingResponse(
                scope=requested_scope,
                status="unsupported_scope",
                objects=[],
                message=f"scope_not_served_by_connector:{requested_scope}",
            )

    try:
        blobs, next_cursor = gcs_client.list_object_page(
            bucket,
            base_prefix=requested_prefix,
            filter_str=config.filter,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        dsx_logging.warning(f"GCS object listing failed: {exc}")
        return ObjectListingResponse(
            scope=requested_scope or bucket,
            status="error",
            objects=[],
            message=f"object_listing_failed:{exc}",
        )

    objects: list[ObjectListingItem] = []
    for blob in blobs:
        key = str(blob.get("Key") or "").strip()
        if not key:
            continue
        identity = f"{bucket}/{key}"
        objects.append(
            ObjectListingItem(
                identity=identity,
                location=key,
                display_name=_relative_to_configured_prefix(key),
                size_in_bytes=blob.get("Size") if isinstance(blob.get("Size"), int) else None,
                metadata={"provider": "gcs", "bucket": bucket},
            )
        )
    return ObjectListingResponse(
        scope=requested_scope or bucket,
        status="success",
        objects=objects,
        next_cursor=next_cursor,
    )


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


def _list_filtered_cloud_asset_inventory_buckets(
    *,
    scope: str,
    limit: int,
    cursor: str | None = None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> tuple[list[AssetDiscoveryItem], str | None]:
    effective_limit = max(1, min(int(limit or 100), 1000))
    if not asset_filter_mode or not asset_filter_value or not asset_filter_value.strip():
        return _list_cloud_asset_inventory_buckets(scope=scope, limit=effective_limit, cursor=cursor)

    selected: list[AssetDiscoveryItem] = []
    current_cursor = cursor
    next_cursor: str | None = None

    while len(selected) < effective_limit:
        remaining = effective_limit - len(selected)
        page_assets, next_cursor = _list_cloud_asset_inventory_buckets(
            scope=scope,
            limit=remaining,
            cursor=current_cursor,
        )
        selected.extend(
            asset
            for asset in page_assets
            if _matches_asset_filter(asset.selector, mode=asset_filter_mode, needle=asset_filter_value)
        )
        if not next_cursor:
            return selected[:effective_limit], None
        current_cursor = next_cursor

    return selected[:effective_limit], next_cursor


@connector.asset_discovery
async def asset_discovery_handler(
    asset_type: str = "bucket",
    source: str = "configured_asset",
    limit: int = 100,
    cursor: str | None = None,
    asset_filter_mode: str | None = None,
    asset_filter_value: str | None = None,
) -> AssetDiscoveryResponse:
    normalized_type = (asset_type or "bucket").strip().lower()
    if ":" in normalized_type:
        normalized_type, requested_source = normalized_type.split(":", 1)
    else:
        requested_source = (source or "configured_asset").strip().lower()
    if normalized_type not in {"bucket", "buckets"}:
        return AssetDiscoveryResponse(
            asset_type=normalized_type,
            source=requested_source,
            status="unsupported",
            assets=[],
            unsupported=True,
            message=f"unsupported_asset_type:{normalized_type}",
        )
    configured_selector = (config.asset or config.asset_bucket or "").strip()
    if requested_source == "configured_asset":
        if not configured_selector:
            return AssetDiscoveryResponse(
                asset_type="bucket",
                source="configured_asset",
                status="not_configured",
                assets=[],
                message="configured_asset_not_set",
            )
        bucket = config.asset_bucket or configured_selector.split("/", 1)[0]
        metadata = {
            "provider": "gcs",
            "kind": "configured_bucket",
            "bucket": bucket,
        }
        if getattr(config, "asset_prefix_root", ""):
            metadata["prefix"] = config.asset_prefix_root
            metadata["kind"] = "configured_bucket_prefix"
        if not _matches_asset_filter(configured_selector, mode=asset_filter_mode, needle=asset_filter_value):
            return AssetDiscoveryResponse(
                asset_type="bucket",
                source="configured_asset",
                status="success",
                assets=[],
            )
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="configured_asset",
            status="success",
            assets=[
                AssetDiscoveryItem(
                    id=configured_selector,
                    display_name=configured_selector,
                    selector=configured_selector,
                    metadata=metadata,
                )
            ],
        )
    asset_inventory_scope = _normalize_asset_inventory_scope(getattr(config, "asset_inventory_scope", ""))
    use_cloud_asset_inventory = requested_source in {"cloud_asset_inventory", "asset_inventory"} or (
        requested_source == "inventory_enumeration" and bool(asset_inventory_scope)
    )
    if use_cloud_asset_inventory:
        try:
            assets, next_cursor = _list_filtered_cloud_asset_inventory_buckets(
                scope=asset_inventory_scope,
                limit=limit,
                cursor=cursor,
                asset_filter_mode=asset_filter_mode,
                asset_filter_value=asset_filter_value,
            )
        except Exception as exc:
            message = str(exc)
            dsx_logging.warning(f"GCS Cloud Asset Inventory discovery failed: {exc}")
            permission_denied = "403" in message or "permission" in message.lower() or "cloudasset" in message.lower()
            return AssetDiscoveryResponse(
                asset_type="bucket",
                source="cloud_asset_inventory",
                status="permission_denied" if permission_denied else "error",
                assets=[],
                unsupported=False,
                message=f"asset_discovery_failed:{exc}",
                required_permission="cloudasset.assets.listResource",
            )
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="cloud_asset_inventory",
            status="success",
            assets=assets,
            next_cursor=next_cursor,
        )

    try:
        buckets = gcs_client.buckets()
    except Exception as exc:
        dsx_logging.warning(f"GCS asset discovery failed: {exc}")
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="inventory_enumeration",
            status="permission_denied" if "storage.buckets.list" in str(exc) or "403" in str(exc) else "error",
            assets=[],
            unsupported=False,
            message=f"asset_discovery_failed:{exc}",
            required_permission="storage.buckets.list",
        )
    start = 0
    if cursor:
        try:
            start = max(0, int(cursor))
        except ValueError:
            start = 0
    buckets = [
        bucket
        for bucket in buckets
        if _matches_asset_filter(bucket, mode=asset_filter_mode, needle=asset_filter_value)
    ]
    effective_limit = max(1, min(int(limit or 100), 1000))
    selected = buckets[start:start + effective_limit]
    next_index = start + len(selected)
    next_cursor = str(next_index) if next_index < len(buckets) else None
    return AssetDiscoveryResponse(
        asset_type="bucket",
        source="inventory_enumeration",
        status="success",
        assets=[
            AssetDiscoveryItem(
                id=bucket,
                display_name=bucket,
                selector=bucket,
                metadata={"provider": "gcs"},
            )
            for bucket in selected
        ],
        next_cursor=next_cursor,
    )


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
    requested_action, target_prefix, requested_tags = _resolve_requested_item_action(scan_event_queue_info)
    preserve_relative_path, resolved_filename = _quarantine_target_config(scan_event_queue_info)
    if not gcs_client.key_exists(config.asset_bucket, file_path):
        return ItemActionStatusResponse(
            status=StatusResponseEnum.ERROR,
            item_action=requested_action,
            message="Item action failed.",
            description=f"File does not exist at {config.asset}: {file_path}",
        )

    if requested_action == ItemActionEnum.DELETE:
        gcs_client.delete_object(config.asset_bucket, file_path)
        return ItemActionStatusResponse(
            status=StatusResponseEnum.SUCCESS,
            item_action=ItemActionEnum.DELETE,
            message="File deleted.",
            description=f"File deleted from {config.asset}: {file_path}",
        )
    if requested_action == ItemActionEnum.MOVE:
        if not target_prefix:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=ItemActionEnum.MOVE,
                message="Item action failed.",
                description="Move action requires a destination path.",
            )
        try:
            dest_key = _resolve_quarantine_object_key(
                source_key=file_path,
                target_prefix=target_prefix,
                preserve_relative_path=preserve_relative_path,
                resolved_filename=resolved_filename,
            )
        except Exception as exc:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=ItemActionEnum.MOVE,
                message="Item action failed.",
                description=str(exc),
            )
        gcs_client.move_object(config.asset_bucket, file_path, config.asset_bucket, dest_key)
        return ItemActionStatusResponse(
            status=StatusResponseEnum.SUCCESS,
            item_action=ItemActionEnum.MOVE,
            message="File moved.",
            description=f"File moved from {config.asset}: {file_path} to {dest_key}",
        )
    if requested_action == ItemActionEnum.TAG:
        gcs_client.tag_object(config.asset_bucket, file_path, requested_tags)
        return ItemActionStatusResponse(
            status=StatusResponseEnum.SUCCESS,
            item_action=ItemActionEnum.TAG,
            message="File tagged.",
            description=f"File tagged at {config.asset}: {file_path}",
        )
    if requested_action == ItemActionEnum.MOVE_TAG:
        if not target_prefix:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=ItemActionEnum.MOVE_TAG,
                message="Item action failed.",
                description="Move/tag action requires a destination path.",
            )
        try:
            dest_key = _resolve_quarantine_object_key(
                source_key=file_path,
                target_prefix=target_prefix,
                preserve_relative_path=preserve_relative_path,
                resolved_filename=resolved_filename,
            )
        except Exception as exc:
            return ItemActionStatusResponse(
                status=StatusResponseEnum.ERROR,
                item_action=ItemActionEnum.MOVE_TAG,
                message="Item action failed.",
                description=str(exc),
            )
        gcs_client.move_object(config.asset_bucket, file_path, config.asset_bucket, dest_key)
        gcs_client.tag_object(config.asset_bucket, dest_key, requested_tags)
        return ItemActionStatusResponse(
            status=StatusResponseEnum.SUCCESS,
            item_action=ItemActionEnum.MOVE_TAG,
            message="File moved and tagged.",
            description=f"File moved from {config.asset}: {file_path} to {dest_key} and tagged.",
        )
    return ItemActionStatusResponse(
        status=StatusResponseEnum.NOTHING,
        item_action=requested_action,
        message="Item action did nothing or not implemented",
    )


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

    changed = (
        apply_requested_action_config_update(
            payload,
            connector_config=config,
            connector_running_model=connector.connector_running_model,
        )
        or changed
    )

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
