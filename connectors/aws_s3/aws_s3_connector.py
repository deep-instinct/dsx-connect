import os
import asyncio
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, File, Form, HTTPException, UploadFile
from starlette.responses import StreamingResponse

import connectors.framework.dsx_connector as connector_framework
from connectors.aws_s3.aws_s3_client import AWSS3Client
from connectors.framework.dsx_connector import DSXConnector, apply_requested_action_config_update, resolve_item_action_request
from connectors.framework.auth_hmac import require_dsx_hmac
from shared.models.connector_models import (
    AssetDiscoveryItem,
    AssetDiscoveryResponse,
    ObjectListingItem,
    ObjectListingResponse,
    ScanRequestModel,
    ItemActionEnum,
    ConnectorInstanceModel,
    ConnectorStatusEnum,
)
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from connectors.aws_s3.config import ConfigManager
from connectors.aws_s3.version import CONNECTOR_VERSION
from shared.file_ops import relpath_matches_filter
from shared.log_sanitizer import config_for_log
import re

# Reload config to pick up environment variables
config = ConfigManager.reload_config()


def _derive_asset_parts(asset_value: str) -> tuple[str, str]:
    raw_asset = (asset_value or "").strip()
    if "/" in raw_asset:
        bucket, prefix = raw_asset.split("/", 1)
        return bucket.strip(), prefix.strip("/")
    return raw_asset, ""


bucket, prefix = _derive_asset_parts(config.asset)
config.asset_bucket = bucket
config.asset_prefix_root = prefix

try:
    config.ng_capabilities = {**(getattr(config, "ng_capabilities", {}) or {}), "write": True}
except Exception:
    pass

connector = DSXConnector(config)

aws_s3_client = AWSS3Client(s3_endpoint_url=config.s3_endpoint_url, s3_endpoint_verify=config.s3_endpoint_verify)


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


def _redact_aws_secret_text(msg: str) -> str:
    if not msg:
        return msg
    redacted = msg
    for key in (
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SESSION_TOKEN",
        "X-Amz-Security-Token",
        "x-amz-security-token",
    ):
        redacted = re.sub(rf"(?i)({key}\s*[:=]\s*)([^,;\\s]+)", rf"\1***", redacted)
    return redacted


def _aws_runtime_value(key: str) -> str:
    return str(os.getenv(key, "") or "")


def _aws_masked_value(key: str) -> str:
    return "**********" if _aws_runtime_value(key) else ""


def _split_bucket_scope(scope: str | None) -> tuple[str, str]:
    raw = str(scope or "").strip().strip("/")
    if not raw:
        return "", ""
    if raw.startswith("s3://"):
        raw = raw[5:].strip("/")
    if "/" not in raw:
        return raw, ""
    bucket_name, key_prefix = raw.split("/", 1)
    return bucket_name.strip(), key_prefix.strip("/")


def _split_s3_destination_path(value: str | None) -> tuple[str, str]:
    return _split_bucket_scope(value)


def _relative_to_configured_prefix(key: str) -> str:
    bp = (config.asset_prefix_root or "").strip("/")
    if not bp:
        return key
    bp = bp + "/"
    return key[len(bp):] if key.startswith(bp) else key


def _resolve_bucket_and_key_for_request(scan_request: ScanRequestModel) -> tuple[str, str]:
    location = str(scan_request.location or "").strip().lstrip("/")
    metainfo = str(scan_request.metainfo or "").strip().strip("/")
    configured_bucket = (config.asset_bucket or "").strip()

    if metainfo and metainfo != location:
        bucket_name, key = _split_bucket_scope(metainfo)
        if bucket_name and key:
            return bucket_name, key
    bucket_name, key = _split_bucket_scope(location)
    if bucket_name and key and (not configured_bucket or bucket_name == configured_bucket):
        return bucket_name, key
    return configured_bucket, location


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
    # Show bucket and optional prefix
    prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, 'asset_prefix_root', '') else ""
    base.meta_info = f"S3 Bucket: {config.asset_bucket}{prefix_disp}, filter: {config.filter or '(none)'}"
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
    def _rel(k: str) -> str:
        bp = (config.asset_prefix_root or "").strip("/")
        if not bp:
            return k
        bp = bp + "/"
        return k[len(bp):] if k.startswith(bp) else k

    count = 0
    batch_items: list[ScanRequestModel] = []
    use_batch = bool(batch)
    effective_batch_size = 1

    if use_batch:
        caps = await connector.get_core_scan_batch_capabilities()
        if not bool(caps.get("enabled", False)):
            dsx_logging.info(
                "Batch full scan requested but core batch mode is disabled; "
                "falling back to single-item enqueue."
            )
            use_batch = False
        else:
            default_size = max(1, int(caps.get("default_size", 10)))
            max_size = max(1, int(caps.get("max_size", 100)))
            requested = batch_size if isinstance(batch_size, int) and batch_size > 0 else default_size
            effective_batch_size = min(max(1, int(requested)), max_size)
            dsx_logging.info(
                f"Using AWS S3 full-scan batch mode: effective_batch_size={effective_batch_size} "
                f"(requested={batch_size}, default={default_size}, max={max_size})"
            )

    async def _flush_batch() -> None:
        nonlocal count, batch_items
        if not batch_items:
            return
        items = batch_items
        batch_items = []
        status_response = await connector.scan_file_request_batch(items, batch_size=effective_batch_size)
        dsx_logging.debug(
            f"Sent batch scan request for {len(items)} item(s), "
            f"result: {status_response}"
        )
        if getattr(status_response, "status", None) == StatusResponseEnum.SUCCESS:
            count += len(items)

    for key in aws_s3_client.keys(config.asset_bucket, base_prefix=config.asset_prefix_root, filter_str=config.filter):
        file_name = key['Key']  # full key
        rel_name = _rel(file_name)
        if config.filter and not relpath_matches_filter(rel_name, config.filter):
            continue
        full_path = f"{config.asset_bucket}/{file_name}"
        req = ScanRequestModel(location=str(file_name), metainfo=full_path)
        if use_batch:
            batch_items.append(req)
            if len(batch_items) >= effective_batch_size or (limit and count + len(batch_items) >= limit):
                await _flush_batch()
        else:
            status_response = await connector.scan_file_request(req)
            dsx_logging.debug(f'Sent scan request for {full_path}, result: {status_response}')
            if getattr(status_response, "status", None) == StatusResponseEnum.SUCCESS:
                count += 1
        if limit and count >= limit:
            break
    if use_batch and batch_items and (not limit or count < limit):
        await _flush_batch()
    dsx_logging.info(f"Full scan enqueued {count} item(s) (asset={config.asset}, filter='{config.filter or ''}')")
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message='Full scan invoked and scan requests sent.', description=f"enqueued={count}")


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

        for obj in aws_s3_client.keys(config.asset_bucket, base_prefix=config.asset_prefix_root, filter_str=config.filter):
            key = obj.get('Key')
            if not key:
                continue
            rel = _rel(key)
            if config.filter and not relpath_matches_filter(rel, config.filter):
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
    if not configured_bucket and not requested_scope:
        return ObjectListingResponse(
            scope=requested_scope,
            status="not_configured",
            objects=[],
            message="asset_bucket_not_configured",
        )

    bucket_name = configured_bucket
    requested_prefix = (config.asset_prefix_root or "").strip("/")
    if requested_scope:
        if requested_scope == configured_bucket:
            requested_prefix = (config.asset_prefix_root or "").strip("/")
        elif configured_bucket and requested_scope.startswith(configured_bucket + "/"):
            requested_prefix = requested_scope[len(configured_bucket) + 1:].strip("/")
        else:
            bucket_name, requested_prefix = _split_bucket_scope(requested_scope)
            if not bucket_name:
                return ObjectListingResponse(
                    scope=requested_scope,
                    status="unsupported_scope",
                    objects=[],
                    message=f"scope_not_served_by_connector:{requested_scope}",
                )

    try:
        objects_page, next_cursor = aws_s3_client.list_object_page(
            bucket_name,
            base_prefix=requested_prefix,
            filter_str=config.filter,
            limit=limit,
            cursor=cursor,
        )
    except Exception as exc:
        dsx_logging.warning(f"S3 object listing failed: {_redact_aws_secret_text(str(exc))}")
        return ObjectListingResponse(
            scope=requested_scope or bucket_name,
            status="error",
            objects=[],
            message=f"object_listing_failed:{_redact_aws_secret_text(str(exc))}",
        )

    listed: list[ObjectListingItem] = []
    for obj in objects_page:
        key = str(obj.get("Key") or "").strip()
        if not key:
            continue
        identity = f"{bucket_name}/{key}"
        metadata = {
            "provider": "s3",
            "bucket": bucket_name,
        }
        for source_key, metadata_key in (
            ("ETag", "etag"),
            ("LastModified", "last_modified"),
            ("StorageClass", "storage_class"),
        ):
            value = obj.get(source_key)
            if value is not None:
                metadata[metadata_key] = str(value)
        listed.append(
            ObjectListingItem(
                identity=identity,
                location=key,
                display_name=_relative_to_configured_prefix(key),
                size_in_bytes=obj.get("Size") if isinstance(obj.get("Size"), int) else None,
                metadata=metadata,
            )
        )
    return ObjectListingResponse(
        scope=requested_scope or bucket_name,
        status="success",
        objects=listed,
        next_cursor=next_cursor,
    )


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

    configured_selector = (config.asset or config.asset_bucket or "").strip().strip("/")

    def configured_asset_item() -> AssetDiscoveryItem | None:
        if not configured_selector:
            return None
        bucket_name = config.asset_bucket or configured_selector.split("/", 1)[0]
        metadata = {
            "provider": "s3",
            "kind": "configured_bucket",
            "bucket": bucket_name,
        }
        if getattr(config, "asset_prefix_root", ""):
            metadata["prefix"] = config.asset_prefix_root
            metadata["kind"] = "configured_bucket_prefix"
        if not _matches_asset_filter(configured_selector, mode=asset_filter_mode, needle=asset_filter_value):
            return None
        return AssetDiscoveryItem(
            id=configured_selector,
            display_name=configured_selector,
            selector=configured_selector,
            metadata=metadata,
        )

    if requested_source == "configured_asset":
        item = configured_asset_item()
        if configured_selector and item is None:
            return AssetDiscoveryResponse(
                asset_type="bucket",
                source="configured_asset",
                status="success",
                assets=[],
            )
        if item is None:
            return AssetDiscoveryResponse(
                asset_type="bucket",
                source="configured_asset",
                status="not_configured",
                assets=[],
                message="configured_asset_not_set",
            )
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="configured_asset",
            status="success",
            assets=[item],
        )

    combined_source = requested_source in {"all", "configured_and_inventory", "configured_plus_inventory"}
    try:
        buckets = aws_s3_client.buckets()
    except Exception as exc:
        message = _redact_aws_secret_text(str(exc))
        dsx_logging.warning(f"S3 asset discovery failed: {message}")
        return AssetDiscoveryResponse(
            asset_type="bucket",
            source="inventory_enumeration",
            status="permission_denied" if "AccessDenied" in message or "403" in message else "error",
            assets=[],
            unsupported=False,
            message=f"asset_discovery_failed:{message}",
            required_permission="s3:ListAllMyBuckets",
        )

    start = 0
    if cursor:
        try:
            start = max(0, int(cursor))
        except ValueError:
            start = 0
    buckets = [
        bucket_name
        for bucket_name in buckets
        if _matches_asset_filter(bucket_name, mode=asset_filter_mode, needle=asset_filter_value)
    ]
    configured_item = configured_asset_item() if combined_source else None
    if configured_item is not None:
        buckets = [bucket_name for bucket_name in buckets if bucket_name != configured_item.selector]
        buckets = [configured_item.selector, *buckets]
    effective_limit = max(1, min(int(limit or 100), 1000))
    selected = buckets[start:start + effective_limit]
    next_index = start + len(selected)
    next_cursor = str(next_index) if next_index < len(buckets) else None
    return AssetDiscoveryResponse(
        asset_type="bucket",
        source=requested_source if combined_source else "inventory_enumeration",
        status="success",
        assets=[
            configured_item
            if configured_item is not None and bucket_name == configured_item.selector
            else AssetDiscoveryItem(
                id=bucket_name,
                display_name=bucket_name,
                selector=bucket_name,
                metadata={"provider": "s3"},
            )
            for bucket_name in selected
        ],
        next_cursor=next_cursor,
    )


@connector.config
async def config_handler(base: ConnectorInstanceModel):
    """Expose runtime config for UI, including AWS credential placeholders."""
    try:
        payload = base.model_dump()
    except Exception:
        from fastapi.encoders import jsonable_encoder
        payload = jsonable_encoder(base)

    extra = {
        "asset": config.asset,
        "filter": config.filter,
        "resolved_asset_base": config.asset,
        "aws_access_key_id": _aws_masked_value("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": _aws_masked_value("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token": _aws_masked_value("AWS_SESSION_TOKEN"),
        "aws_default_region": _aws_runtime_value("AWS_DEFAULT_REGION"),
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


@connector.config_update
async def config_update_handler(payload: dict):
    """Update runtime-editable connector config fields and persist for local runs when enabled."""
    changed = False

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

    aws_updates: dict[str, str] = {}
    secret_payload_keys = ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")
    nonsecret_payload_keys = ("aws_default_region",)
    key_map = {
        "aws_access_key_id": "AWS_ACCESS_KEY_ID",
        "aws_secret_access_key": "AWS_SECRET_ACCESS_KEY",
        "aws_session_token": "AWS_SESSION_TOKEN",
        "aws_default_region": "AWS_DEFAULT_REGION",
    }

    for pkey in secret_payload_keys:
        if isinstance(payload.get(pkey), str):
            val = payload.get(pkey, "")
            # Blank means keep existing (write-only behavior for secrets).
            if val:
                aws_updates[key_map[pkey]] = val
                changed = True

    for pkey in nonsecret_payload_keys:
        if isinstance(payload.get(pkey), str):
            val = payload.get(pkey, "").strip()
            aws_updates[key_map[pkey]] = val
            changed = True

    if not changed:
        return {
            "error": "no_supported_fields",
            "supported": [
                "asset",
                "filter",
                "item_action",
                "item_action_move_metainfo",
                "aws_access_key_id",
                "aws_secret_access_key",
                "aws_session_token",
                "aws_default_region",
            ],
        }

    # Keep derived parts aligned with current asset.
    bucket, prefix = _derive_asset_parts(config.asset)
    config.asset_bucket = bucket
    config.asset_prefix_root = prefix

    # Keep running model in sync for UI and downstream handlers.
    try:
        connector.connector_running_model.asset = config.asset
        connector.connector_running_model.filter = config.filter
        connector.connector_running_model.item_action = config.item_action
        connector.connector_running_model.item_action_move_metainfo = config.item_action_move_metainfo
        prefix_disp = f"/{config.asset_prefix_root}" if getattr(config, 'asset_prefix_root', '') else ""
        connector.connector_running_model.meta_info = f"S3 Bucket: {config.asset_bucket}{prefix_disp}, filter: {config.filter or '(none)'}"
    except Exception:
        pass

    # Keep singleton in sync for components that call ConfigManager.get_config().
    try:
        ConfigManager._config = config
    except Exception:
        pass

    # Persist only for local runtime envs (e.g., ~/.dsx-connect-local/*/.env.local)
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
        persist_updates.update(aws_updates)
        persisted, persist_detail = ConfigManager.persist_runtime_overrides(persist_updates)
    except Exception as e:
        persisted = False
        persist_detail = f"persist_error:{type(e).__name__}"

    # Keep process env in sync even when persistence is skipped.
    for k, v in aws_updates.items():
        os.environ[k] = v

    persistence_message = (
        f"persisted to {persist_detail}" if persisted else f"runtime-only ({persist_detail})"
    )

    out = await config_handler(connector.connector_running_model)
    out["persistence"] = {
        "applied": persisted,
        "detail": persist_detail,
    }
    out["note"] = f"S3 config update applied; {persistence_message}"
    return out


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
    bucket_name, source_key = _resolve_bucket_and_key_for_request(scan_event_queue_info)
    full_path = scan_event_queue_info.metainfo or f"{bucket_name}/{source_key}"
    requested_action, target_prefix, target_filename, requested_tags = _resolve_requested_item_action(scan_event_queue_info)

    if not aws_s3_client.key_exists(bucket_name, source_key):
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                        message="Item action failed.",
                                        description=f"File does not exist at {full_path}")

    if requested_action == ItemActionEnum.DELETE:
        dsx_logging.debug(f'Item action {ItemActionEnum.DELETE} on {full_path} invoked.')
        if aws_s3_client.delete_object(bucket_name, source_key):
            return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                            message="File deleted.",
                                            description=f"File deleted from {bucket_name}: {source_key}")
    elif requested_action == ItemActionEnum.MOVE:
        dsx_logging.debug(f'Item action {ItemActionEnum.MOVE} on {full_path} invoked.')
        if not target_prefix:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                            message="Item action failed.",
                                            description="Move action requires a destination path.")
        dest_key = _resolve_destination_key(source_key, target_prefix=target_prefix, target_filename=target_filename)
        aws_s3_client.move_object(src_bucket=bucket_name, src_key=source_key,
                                  dest_bucket=bucket_name,
                                  dest_key=dest_key)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File moved.",
                                        description=f"File moved from {bucket_name}: {source_key} to {bucket_name}: {dest_key}")
    elif requested_action == ItemActionEnum.TAG:
        dsx_logging.debug(f'Item action {ItemActionEnum.TAG} on {full_path} invoked.')
        aws_s3_client.tag_object(bucket_name, source_key, tags=requested_tags)
        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message="File tagged.",
                                        description=f"File tagged at {bucket_name}: {source_key}")
    elif requested_action == ItemActionEnum.MOVE_TAG:
        dsx_logging.debug(f'Item action {ItemActionEnum.MOVE_TAG} on {full_path} invoked.')
        if not target_prefix:
            return ItemActionStatusResponse(status=StatusResponseEnum.ERROR, item_action=requested_action,
                                            message="Item action failed.",
                                            description="Move/tag action requires a destination path.")
        dest_key = _resolve_destination_key(source_key, target_prefix=target_prefix, target_filename=target_filename)

        aws_s3_client.move_object(src_bucket=bucket_name, src_key=source_key,
                                  dest_bucket=bucket_name, dest_key=dest_key)

        aws_s3_client.tag_object(bucket_name, dest_key, tags=requested_tags)

        return ItemActionStatusResponse(status=StatusResponseEnum.SUCCESS, item_action=requested_action,
                                        message=f'Item action {requested_action} was invoked. File {full_path} successfully tagged.')

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
    # Read the file content
    try:
        bucket_name, key = _resolve_bucket_and_key_for_request(scan_event_queue_info)
        body, size_bytes = aws_s3_client.get_object_stream(
            bucket=bucket_name,
            key=key,
        )

        def _iter_s3_body():
            try:
                while True:
                    chunk = body.read(getattr(aws_s3_client, "_chunk_size", 1024 * 1024))
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    body.close()
                except Exception:
                    pass

        headers = {}
        if size_bytes is not None:
            headers["Content-Length"] = str(size_bytes)
        return StreamingResponse(
            _iter_s3_body(),
            media_type="application/octet-stream",
            headers=headers,
        )
    except Exception as e:
        err = _redact_aws_secret_text(str(e))
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message=f"Failed to read file: {err}")


@connector_framework.connector_api.post(
    f"/{connector.connector_running_model.name}/write_file",
    dependencies=[Depends(require_dsx_hmac)],
)
async def write_file_handler(
    bucket: Annotated[str | None, Form()] = None,
    key: Annotated[str | None, Form()] = None,
    destination: Annotated[str | None, Form()] = None,
    file: UploadFile = File(...),
) -> dict:
    resolved_bucket = str(bucket or "").strip()
    resolved_key = str(key or "").strip().strip("/")
    if destination and (not resolved_bucket or not resolved_key):
        destination_bucket, destination_key = _split_s3_destination_path(destination)
        resolved_bucket = resolved_bucket or destination_bucket
        resolved_key = resolved_key or destination_key
    if not resolved_bucket or not resolved_key:
        raise HTTPException(status_code=400, detail="bucket_and_key_required")

    suffix = Path(file.filename or resolved_key).suffix
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="dsx-s3-write-", suffix=suffix, delete=False) as handle:
            tmp_path = Path(handle.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        aws_s3_client.upload_file(tmp_path, file_key=resolved_key, bucket=resolved_bucket)
        return {
            "status": "success",
            "bucket": resolved_bucket,
            "key": resolved_key,
            "uri": f"s3://{resolved_bucket}/{resolved_key}",
        }
    except Exception as exc:
        dsx_logging.error(f"S3 write_file error: {_redact_aws_secret_text(str(exc))}")
        raise HTTPException(status_code=500, detail=_redact_aws_secret_text(str(exc))) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    """
    Repository connectivity check handler.

    This handler verifies that the configured repository location exists and this DSX Connector can connect to it.

    Returns:
        bool: True if the repository connectivity OK, False otherwise.
    """
    if aws_s3_client.test_s3_connection(config.asset_bucket):
        return StatusResponse(
            status=StatusResponseEnum.SUCCESS,
            message=f"Connection to bucket: {config.asset_bucket} successful",
            description=""
        )

    return StatusResponse(
        status=StatusResponseEnum.ERROR,
        message=f"Connection to bucket: {config.asset_bucket} NOT successful",
        description=""
    )


@connector.webhook_event
async def webhook_handler(event: dict):
    """
    Webhook Event handler for the DSX Connector.

    This function is invoked by external systems (e.g., third-party file repositories or notification services)
    when a new file event occurs. The connector should extract the necessary file details from the event payload
    (for example, a file ID or name) and trigger a scan request via DSX Connect using the connector.scan_file_request method.

    Handles AWS S3-style event:
    {
        "Records": [
            {
                "s3": {
                    "bucket": { "name": "my-bucket" },
                    "object": { "key": "path/to/file.txt" }
                }
            }
        ]
    }

    Args:
        event (dict): The JSON payload sent by the external system containing file event details.

    Returns:
        SimpleResponse: A response indicating that the webhook was processed and the file scan request has been initiated,
            or an error if processing fails.

    """
    dsx_logging.debug(f"Processing webhook event: {event}")
    try:
        record = event["Records"][0]
        s3 = record["s3"]
        bucket = s3["bucket"]["name"]
        key = s3["object"]["key"]

        if not bucket or not key:
            raise ValueError("Missing bucket or key in S3 event")

        location = f"{key}"
        metainfo = str({"bucket": bucket, "key": key})

        # Ignore events for other buckets
        if bucket and config.asset_bucket and bucket != config.asset_bucket:
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="S3 webhook processed", description=f"Ignored by bucket mismatch: {bucket}")

        # Apply connector base prefix and filter (relative)
        bp = (config.asset_prefix_root or "").strip("/")
        bp = (bp + "/") if bp else ""
        rel = key[len(bp):] if (bp and key.startswith(bp)) else key
        if bp and not key.startswith(bp):
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="S3 webhook processed", description=f"Ignored by base prefix: {key}")
        if config.filter and not relpath_matches_filter(rel, config.filter):
            return StatusResponse(status=StatusResponseEnum.SUCCESS, message="S3 webhook processed", description=f"Ignored by filter: {key}")

        dsx_logging.info(f"Received S3 event for {location}")
        response = await connector.scan_file_request(
            ScanRequestModel(location=location, metainfo=metainfo)
        )

        return StatusResponse(
            status=response.status,
            message="S3 webhook processed",
            description=f"Scan request sent for {location}"
        )
    except (KeyError, IndexError, TypeError) as parse_err:
        dsx_logging.error(f"Malformed S3 event payload: {_redact_aws_secret_text(str(parse_err))}")
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Invalid S3 event format",
            description=_redact_aws_secret_text(str(parse_err))
        )
    except Exception as e:
        redacted = _redact_aws_secret_text(str(e))
        dsx_logging.error(f"Unexpected error in webhook handler: {redacted}", exc_info=True)
        return StatusResponse(
            status=StatusResponseEnum.ERROR,
            message="Internal error during webhook handling",
            description=redacted
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("connectors.framework.dsx_connector:connector_api", host="0.0.0.0",
                port=8591, reload=False)
