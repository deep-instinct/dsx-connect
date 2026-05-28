from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Awaitable, Callable

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import MessageEnvelope, ScanItemRequested
from dsx_connect_ng.jobs.models import ScanResult, ScanStageUpdateRequest
from dsx_connect_ng.ops_logging import log_event, ops_logging
from dsx_connect_ng.readers.base import Reader, TerminalScanError
from dsx_connect_ng.readers.local_path import LocalPathReader
from dsx_connect_ng.readers.resolver import build_scan_reader
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


ScanExecutor = Callable[[ScanItemRequested, Reader], Awaitable[ScanResult]]


def _import_dsxa_client():
    try:
        from dsxa_sdk_py.client import AsyncDSXAClient
        from dsxa_sdk_py.exceptions import AuthenticationError, BadRequestError, DSXAError, NotFoundError, ServerError
        from dsxa_sdk_py.models import ScanResponse
        return AsyncDSXAClient, ScanResponse, DSXAError, AuthenticationError, BadRequestError, NotFoundError, ServerError
    except ImportError:
        repo_root = Path(__file__).resolve().parents[3]
        candidate = repo_root / "dsxa_sdk_py"
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        from dsxa_sdk_py.client import AsyncDSXAClient
        from dsxa_sdk_py.exceptions import AuthenticationError, BadRequestError, DSXAError, NotFoundError, ServerError
        from dsxa_sdk_py.models import ScanResponse
        return AsyncDSXAClient, ScanResponse, DSXAError, AuthenticationError, BadRequestError, NotFoundError, ServerError

def resolve_local_scan_path(request: ScanItemRequested) -> Path:
    return LocalPathReader().resolve_path(request)


def _encode_custom_metadata_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    try:
        text.encode("ascii")
        return text
    except UnicodeEncodeError:
        return urllib.parse.quote(text, safe="")


def build_scan_custom_metadata(request: ScanItemRequested, *, reader_name: str, reader_details: dict | None = None) -> str:
    scan_options = getattr(request, "scan_options", {}) or {}
    explicit = scan_options.get("customMetadata") or scan_options.get("custom_metadata")
    parts: list[str] = []
    object_identity = _encode_custom_metadata_value(getattr(request, "object_identity", None))
    if object_identity:
        parts.append(f"object-identity:{object_identity}")
    content_source = getattr(request, "content_source", None)
    if content_source is not None and getattr(content_source, "mode", None):
        parts.append(f"content-source:{_encode_custom_metadata_value(content_source.mode)}")
    if content_source is not None and getattr(content_source, "locator", None):
        parts.append(f"source-locator:{_encode_custom_metadata_value(content_source.locator)}")
    integration_id = getattr(request, "integration_id", None)
    if integration_id:
        parts.append(f"integration-id:{_encode_custom_metadata_value(integration_id)}")
    scope_id = getattr(request, "scope_id", None)
    if scope_id:
        parts.append(f"scope-id:{_encode_custom_metadata_value(scope_id)}")
    job_id = getattr(request, "job_id", None)
    if job_id:
        parts.append(f"job-id:{_encode_custom_metadata_value(job_id)}")
    job_item_id = getattr(request, "job_item_id", None)
    if job_item_id:
        parts.append(f"job-item-id:{_encode_custom_metadata_value(job_item_id)}")
    if reader_name:
        parts.append(f"reader:{_encode_custom_metadata_value(reader_name)}")
    if reader_details:
        endpoint_url = reader_details.get("endpointUrl")
        if endpoint_url:
            parts.append(f"connector-endpoint:{_encode_custom_metadata_value(endpoint_url)}")
    if explicit:
        parts.append(f"user-meta:{_encode_custom_metadata_value(explicit)}")
    return ",".join(parts)


def map_dsxa_scan_response(response) -> ScanResult:
    payload = response.model_dump(mode="json", by_alias=True) if hasattr(response, "model_dump") else {
        "scan_guid": response.scan_guid,
        "verdict": response.verdict.value if hasattr(response.verdict, "value") else str(response.verdict),
        "verdict_details": response.verdict_details.model_dump(mode="json", by_alias=True),
        "file_info": response.file_info.model_dump(mode="json") if response.file_info is not None else None,
        "protected_entity": response.protected_entity,
        "scan_duration_in_microseconds": response.scan_duration_in_microseconds,
        "container_files_scanned": response.container_files_scanned,
        "container_files_scanned_size": response.container_files_scanned_size,
        "X-Custom-Metadata": response.x_custom_metadata,
        "last_update_time": response.last_update_time,
    }
    return ScanResult.model_validate(payload)


def _classify_dsxa_transport_error(exc: Exception) -> tuple[str, str]:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "scanner_timeout", message
    if "connect" in lowered or "connection" in lowered or "network" in lowered:
        return "scanner_transport_failure", message
    return "scanner_unavailable", message


def _extract_size_hint_bytes(request: ScanItemRequested) -> int | None:
    read_hint = getattr(request, "read_hint", {}) or {}
    for key in ("sizeInBytes", "size_in_bytes"):
        value = read_hint.get(key)
        if isinstance(value, int):
            return value
    return None


async def execute_scan_via_dsxa(request: ScanItemRequested, reader: Reader) -> ScanResult:
    base_url = settings.scanner.base_url.rstrip("/")
    if not base_url:
        raise TerminalScanError("scanner_base_url_required", "DSX_CONNECT_NG_SCANNER__BASE_URL is required for dsxa scan mode")
    max_file_size = settings.scanner.max_file_size_bytes
    size_hint = _extract_size_hint_bytes(request)
    if max_file_size and size_hint is not None and size_hint > max_file_size:
        raise TerminalScanError(
            "content_too_large",
            "scan skipped because content size hint exceeds scanner limit",
            details={
                "sizeInBytes": size_hint,
                "maxFileSizeBytes": max_file_size,
                "enforcement": "size_hint",
            },
        )
    read_started = time.perf_counter()
    read_result = await reader.acquire(request)
    read_elapsed_ms = (time.perf_counter() - read_started) * 1000.0
    if max_file_size and read_result.content_length is not None and read_result.content_length > max_file_size:
        raise TerminalScanError(
            "content_too_large",
            "scan skipped because content size exceeds scanner limit",
            details={
                "sizeInBytes": read_result.content_length,
                "maxFileSizeBytes": max_file_size,
                "enforcement": "read_result",
            },
        )
    if read_result.local_path is None:
        raise TerminalScanError("reader_local_path_required", "current dsxa scan mode requires a local reader path", details=read_result.details)
    file_path = read_result.local_path
    protected_entity = request.scan_options.get("protectedEntity") or request.scan_options.get("protected_entity")
    custom_metadata = build_scan_custom_metadata(
        request,
        reader_name=read_result.details.get("reader") or reader.__class__.__name__,
        reader_details=read_result.details,
    )
    password = request.scan_options.get("password")
    (
        AsyncDSXAClient,
        _ScanResponse,
        DSXAError,
        AuthenticationError,
        BadRequestError,
        NotFoundError,
        ServerError,
    ) = _import_dsxa_client()
    dsxa_started = time.perf_counter()
    try:
        async with AsyncDSXAClient(
            base_url=base_url,
            auth_token=settings.scanner.auth_token,
            timeout=settings.scanner.timeout_seconds,
            verify_tls=settings.scanner.verify_tls,
            default_protected_entity=settings.scanner.protected_entity,
        ) as client:
            response = await client.scan_file(
                str(file_path),
                protected_entity=protected_entity,
                custom_metadata=custom_metadata,
                password=password,
            )
    except AuthenticationError as exc:
        raise TerminalScanError("scanner_auth_failed", str(exc), details={"baseUrl": base_url}) from exc
    except BadRequestError as exc:
        raise TerminalScanError(
            "scanner_request_invalid",
            str(exc),
            details={
                "baseUrl": base_url,
                "protectedEntity": protected_entity,
            },
        ) from exc
    except NotFoundError as exc:
        raise TerminalScanError("scanner_resource_not_found", str(exc), details={"baseUrl": base_url}) from exc
    except ServerError as exc:
        code, message = _classify_dsxa_transport_error(exc)
        raise RuntimeError(f"{code}: {message}") from exc
    except DSXAError as exc:
        code, message = _classify_dsxa_transport_error(exc)
        raise RuntimeError(f"{code}: {message}") from exc
    dsxa_elapsed_ms = (time.perf_counter() - dsxa_started) * 1000.0
    result = map_dsxa_scan_response(response)
    request.scan_options["_dsx_scanner_metadata"] = {
        "source": "dsxa",
        "reader": read_result.details.get("reader"),
        "contentSourceMode": request.content_source.mode,
        "readerElapsedMs": round(read_elapsed_ms, 3),
        "requestElapsedMs": getattr(response, "dsxconnect_request_elapsed_ms", None) or round(read_elapsed_ms + dsxa_elapsed_ms, 3),
        "readElapsedMs": getattr(response, "dsxconnect_read_elapsed_ms", None),
        "dsxaElapsedMs": getattr(response, "dsxconnect_dsxa_elapsed_ms", None) or round(dsxa_elapsed_ms, 3),
        "protectedEntity": result.protected_entity,
    }
    return result


def resolve_scan_executor() -> ScanExecutor:
    mode = settings.scanner.mode
    if mode == "stub":
        return stub_scan_executor
    if mode == "dsxa":
        return execute_scan_via_dsxa
    if settings.scanner.base_url.strip():
        return execute_scan_via_dsxa
    return stub_scan_executor


async def process_scan_message(
    service: JobService,
    envelope: MessageEnvelope,
    *,
    execute_scan: ScanExecutor,
) -> None:
    request = ScanItemRequested.from_envelope(envelope)
    reader = build_scan_reader(request, control_plane=service.control_plane)
    log_event(
        ops_logging,
        20,
        "scan_item_started",
        job_id=request.job_id,
        job_item_id=request.job_item_id,
        integration_id=request.integration_id,
        scope_id=request.scope_id,
        object_identity=request.object_identity,
        content_source_mode=request.content_source.mode,
        reader=reader.__class__.__name__,
        scan_mode=settings.scanner.mode,
    )
    service.update_scan_stage(
        request.job_item_id,
        ScanStageUpdateRequest(state="running").as_stage_update_request(),
    )
    try:
        result = await execute_scan(request, reader)
    except TerminalScanError as exc:
        log_event(
            ops_logging,
            30,
            "scan_item_terminal_failure",
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            object_identity=request.object_identity,
            error=exc.as_error_payload(),
        )
        service.update_scan_stage(
            request.job_item_id,
            ScanStageUpdateRequest(state="failed", error=exc.as_error_payload()).as_stage_update_request(),
        )
        return
    except Exception as exc:
        log_event(
            ops_logging,
            40,
            "scan_item_retryable_failure",
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            object_identity=request.object_identity,
            error={
                "code": "scan_execution_failed",
                "message": str(exc),
                "retryable": True,
            },
        )
        raise
    scan_stage_request = ScanStageUpdateRequest(
        state="completed",
        scan_result=result,
        scanner_metadata=request.scan_options.get("_dsx_scanner_metadata") or {},
    ).as_stage_update_request()
    service.update_scan_stage(
        request.job_item_id,
        scan_stage_request,
    )
    log_event(
        ops_logging,
        20,
        "scan_item_completed",
        job_id=request.job_id,
        job_item_id=request.job_item_id,
        object_identity=request.object_identity,
        verdict=result.verdict,
        scan_guid=result.scan_guid,
        file_type=result.file_type,
        scanner_metadata=scan_stage_request.metadata,
    )
    await service.request_policy_evaluation(request.job_item_id)
    log_event(
        ops_logging,
        20,
        "policy_evaluation_requested",
        job_id=request.job_id,
        job_item_id=request.job_item_id,
        object_identity=request.object_identity,
    )


async def stub_scan_executor(request: ScanItemRequested, _reader: Reader) -> ScanResult:
    scan_options = request.scan_options or {}
    verdict = scan_options.get("mockVerdict", "Benign")
    return ScanResult(
        verdict=verdict,
        scanGuid=scan_options.get("mockScanGuid", f"scan-{request.job_item_id}"),
        fileType=scan_options.get("mockFileType"),
        scanDurationUs=scan_options.get("mockScanDurationUs"),
        details={"worker": "scan_stub"},
        scannerMetadata={"source": "scan_worker"},
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume scan work queue and post scan-stage callbacks.")
    parser.add_argument("--queue", default="dsx.ng.scan", help="RabbitMQ work queue to consume.")
    parser.add_argument("--routing-key", default="scan.requested", help="Routing key to bind.")
    parser.add_argument("--prefetch-count", type=int, default=1, help="Consumer prefetch count.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    executor = resolve_scan_executor()
    executor_name = getattr(executor, "__name__", executor.__class__.__name__)
    print(
        json.dumps(
            {
                "event": "scan_worker_start",
                **summary,
                "queue": args.queue,
                "scan_executor": executor_name,
                "default_reader_strategy": settings.readers.default_strategy,
            }
        ),
        flush=True,
    )

    async def handle(envelope: MessageEnvelope) -> None:
        await process_scan_message(service, envelope, execute_scan=executor)

    await consume_queue(
        amqp_url=settings.rabbitmq.url,
        exchange_name=settings.rabbitmq.job_exchange,
        queue_name=args.queue,
        routing_keys=[args.routing_key],
        handler=handle,
        prefetch_count=args.prefetch_count,
        retry_exchange_name=settings.rabbitmq.retry_exchange,
        dead_letter_exchange_name=settings.rabbitmq.dead_letter_exchange,
        retry_delay_ms=settings.rabbitmq.retry_delay_ms,
        retry_max_attempts=settings.rabbitmq.retry_max_attempts,
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
