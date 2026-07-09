from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterable, Awaitable, Callable

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import MessageEnvelope, ScanItemRequested
from dsx_connect_ng.jobs.models import ScanResult, ScanStageUpdateRequest, StageUpdateRequest
from dsx_connect_ng.ops_logging import log_event, ops_logging
from dsx_connect_ng.readers.base import Reader, TerminalScanError
from dsx_connect_ng.readers.local_path import LocalPathReader
from dsx_connect_ng.readers.resolver import build_scan_reader
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


ScanExecutor = Callable[[ScanItemRequested, Reader], Awaitable[ScanResult]]
_CANCELLED_JOB_IDS: set[str] = set()
_CANCELLED_JOB_SKIP_COUNTS: dict[str, int] = {}
_DSXA_CLIENT: Any | None = None
_DSXA_CLIENT_KEY: tuple[Any, ...] | None = None
_SCANNER_CLIENT_SCOPE = "shared"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


_SCAN_BATCH_ITEM_LOGGING = _env_bool("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ITEM_LOGGING", True)


def _log_scan_batch_item_event(level: int, event: str, **fields: Any) -> None:
    if _SCAN_BATCH_ITEM_LOGGING:
        log_event(ops_logging, level, event, **fields)


async def _service_io(threaded: bool, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if threaded:
        return await asyncio.to_thread(func, *args, **kwargs)
    return func(*args, **kwargs)


def is_scan_only_request(request: ScanItemRequested) -> bool:
    return request.scan_options.get("scanOnly") is True or request.scan_options.get("scan_only") is True


def uses_coarse_durable_scan_progress(request: ScanItemRequested) -> bool:
    scan_progress_mode = request.scan_options.get("scanProgressMode") or request.scan_options.get("scan_progress_mode")
    if scan_progress_mode in {"item", "fine", "fine_grained"}:
        return False
    if scan_progress_mode in {"batch", "coarse", "coarse_grained"}:
        return True
    recovery_mode = request.scan_options.get("effectiveRecoveryMode") or request.scan_options.get("effective_recovery_mode")
    return is_scan_only_request(request) and recovery_mode != "item"


@dataclass
class StreamTiming:
    elapsed_ms: float = 0.0
    bytes_read: int = 0
    chunks: int = 0


class ScanOnlyCompletionBuffer:
    def __init__(self, service: JobService, *, batch_size: int, flush_interval_seconds: float) -> None:
        self.service = service
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = max(0.05, flush_interval_seconds)
        self._pending: list[tuple[str, str, StageUpdateRequest]] = []
        self._lock = asyncio.Lock()
        self._last_flush = time.perf_counter()

    async def add(self, *, job_id: str, job_item_id: str, payload: StageUpdateRequest) -> None:
        async with self._lock:
            self._pending.append((job_id, job_item_id, payload))
            if len(self._pending) < self.batch_size:
                return
            pending = self._drain_locked()
        await self._flush_pending(pending)

    async def flush_due(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            if time.perf_counter() - self._last_flush < self.flush_interval_seconds:
                return
            pending = self._drain_locked()
        await self._flush_pending(pending)

    async def flush_all(self) -> None:
        async with self._lock:
            pending = self._drain_locked()
        await self._flush_pending(pending)

    def _drain_locked(self) -> list[tuple[str, str, StageUpdateRequest]]:
        pending = self._pending
        self._pending = []
        self._last_flush = time.perf_counter()
        return pending

    async def _flush_pending(self, pending: list[tuple[str, str, StageUpdateRequest]]) -> None:
        if not pending:
            return
        started = time.perf_counter()
        count = await asyncio.to_thread(self.service.complete_scan_only_bulk, pending, refresh_parent=False)
        log_event(
            ops_logging,
            20,
            "scan_only_completion_buffer_flushed",
            attempted=len(pending),
            completed=count,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
            batch_size=self.batch_size,
        )


@dataclass
class ScanOnlyBatchEntry:
    request: ScanItemRequested
    future: asyncio.Future[None]
    accepted_at: float
    scan_started_at: float | None = None
    scan_finished_at: float | None = None


class ScanOnlyBatchCoordinator:
    def __init__(
        self,
        service: JobService,
        *,
        execute_scan: ScanExecutor,
        batch_size: int,
        max_wait_seconds: float,
        scan_concurrency: int,
        scan_only_runtime_leases: bool,
        service_io_threaded: bool,
        ack_mode: str = "completed",
        trust_items: bool = False,
    ) -> None:
        self.service = service
        self.execute_scan = execute_scan
        self.batch_size = max(1, batch_size)
        self.max_wait_seconds = max(0.001, max_wait_seconds)
        self.scan_concurrency = max(1, scan_concurrency)
        self.scan_only_runtime_leases = scan_only_runtime_leases
        self.service_io_threaded = service_io_threaded
        self.ack_mode = ack_mode
        self.trust_items = trust_items
        self._pending: list[ScanOnlyBatchEntry] = []
        self._active = 0
        self._completion_pending: list[tuple[ScanOnlyBatchEntry, tuple[str, str, StageUpdateRequest]]] = []
        self._lock = asyncio.Lock()
        self._flush_timer: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_requested = False
        self._scan_tasks: set[asyncio.Task[None]] = set()

    async def add(self, envelope: MessageEnvelope) -> None:
        request = ScanItemRequested.from_envelope(envelope)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        entry = ScanOnlyBatchEntry(request=request, future=future, accepted_at=time.perf_counter())
        async with self._lock:
            self._pending.append(entry)
            _log_scan_batch_item_event(
                20,
                "scan_only_batch_message_accepted",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
                ack_mode=self.ack_mode,
                pending=len(self._pending),
                active=self._active,
                completion_pending=len(self._completion_pending),
                scan_concurrency=self.scan_concurrency,
            )
            self._pump_locked()
        if self.ack_mode == "accepted":
            future.add_done_callback(self._log_unobserved_failure)
            _log_scan_batch_item_event(
                20,
                "scan_only_batch_message_ack_ready",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
                ack_mode=self.ack_mode,
                elapsed_since_accept_ms=round((time.perf_counter() - entry.accepted_at) * 1000.0, 3),
                future_done=future.done(),
            )
            return
        await future
        _log_scan_batch_item_event(
            20,
            "scan_only_batch_message_ack_ready",
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            object_identity=request.object_identity,
            ack_mode=self.ack_mode,
            elapsed_since_accept_ms=round((time.perf_counter() - entry.accepted_at) * 1000.0, 3),
            future_done=future.done(),
        )

    def _log_unobserved_failure(self, future: asyncio.Future[None]) -> None:
        try:
            future.result()
        except Exception as exc:
            log_event(
                ops_logging,
                40,
                "scan_only_batch_async_failure_after_ack",
                error={"code": "scan_only_batch_async_failure_after_ack", "message": str(exc)},
            )

    async def flush_all(self) -> None:
        while True:
            async with self._lock:
                if not self._pending and self._active == 0:
                    break
                self._pump_locked()
            await asyncio.sleep(0.01)
        async with self._lock:
            self._flush_requested = True
            self._ensure_completion_flush_task_locked()
            flush_task = self._flush_task
        if flush_task is not None:
            await flush_task
        if self._scan_tasks:
            await asyncio.gather(*self._scan_tasks, return_exceptions=True)

    def _pump_locked(self) -> None:
        while self._pending and self._active < self.scan_concurrency:
            entry = self._pending.pop(0)
            self._active += 1
            _log_scan_batch_item_event(
                20,
                "scan_only_batch_active_count_changed",
                job_id=entry.request.job_id,
                job_item_id=entry.request.job_item_id,
                object_identity=entry.request.object_identity,
                active=self._active,
                pending=len(self._pending),
                completion_pending=len(self._completion_pending),
                scan_concurrency=self.scan_concurrency,
                reason="scan_scheduled",
            )
            task = asyncio.create_task(self._run_one(entry))
            self._scan_tasks.add(task)
            task.add_done_callback(self._scan_tasks.discard)

    def _drain_completions_locked(self) -> list[tuple[ScanOnlyBatchEntry, tuple[str, str, StageUpdateRequest]]]:
        completions = self._completion_pending
        self._completion_pending = []
        if self._flush_timer is not None and not self._flush_timer.done():
            self._flush_timer.cancel()
        self._flush_timer = None
        return completions

    def _ensure_completion_flush_task_locked(self) -> None:
        if not self._completion_pending:
            return
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_task = asyncio.create_task(self._completion_flush_loop())

    async def _completion_flush_loop(self) -> None:
        while True:
            async with self._lock:
                if not self._completion_pending:
                    self._flush_requested = False
                    self._flush_task = None
                    return
                if len(self._completion_pending) < self.batch_size and not self._flush_requested:
                    if self._flush_timer is None or self._flush_timer.done():
                        self._flush_timer = asyncio.create_task(self._flush_later())
                    self._flush_task = None
                    return
                completions = self._drain_completions_locked()
                self._flush_requested = False
                active = self._active
                pending = len(self._pending)
                completion_pending = len(self._completion_pending)
            log_event(
                ops_logging,
                20,
                "scan_only_batch_completion_flush_scheduled",
                attempted=len(completions),
                active=active,
                pending=pending,
                completion_pending=completion_pending,
                batch_size=self.batch_size,
            )
            await self._flush_completions(completions)

    def _resolve_entry_future(self, entry: ScanOnlyBatchEntry, *, result: str, exc: Exception | None = None) -> None:
        if entry.future.done():
            return
        if exc is None:
            entry.future.set_result(None)
        else:
            entry.future.set_exception(exc)
        _log_scan_batch_item_event(
            20 if exc is None else 40,
            "scan_only_batch_future_resolved",
            job_id=entry.request.job_id,
            job_item_id=entry.request.job_item_id,
            object_identity=entry.request.object_identity,
            result=result,
            ack_mode=self.ack_mode,
            elapsed_since_accept_ms=round((time.perf_counter() - entry.accepted_at) * 1000.0, 3),
            scan_elapsed_ms=(
                round((entry.scan_finished_at - entry.scan_started_at) * 1000.0, 3)
                if entry.scan_started_at is not None and entry.scan_finished_at is not None
                else None
            ),
            error={"code": result, "message": str(exc)} if exc is not None else None,
        )

    async def _flush_later(self) -> None:
        try:
            await asyncio.sleep(self.max_wait_seconds)
            async with self._lock:
                self._flush_timer = None
                self._flush_requested = True
                self._ensure_completion_flush_task_locked()
        except asyncio.CancelledError:
            return

    async def _scan_one(self, entry: ScanOnlyBatchEntry) -> tuple[str, str, StageUpdateRequest] | None:
        request = entry.request
        use_runtime_lease = self.scan_only_runtime_leases
        if not self.trust_items:
            if request.job_id in _CANCELLED_JOB_IDS:
                self._resolve_entry_future(entry, result="cancelled_parent_cached")
                return None
            current_item = await _service_io(self.service_io_threaded, self.service.get_job_item_or_404, request.job_item_id)
            job_cancelled = await _service_io(self.service_io_threaded, self.service.is_job_cancelled, request.job_id)
            if job_cancelled:
                _CANCELLED_JOB_IDS.add(request.job_id)
                _CANCELLED_JOB_SKIP_COUNTS.setdefault(request.job_id, 0)
            if current_item.state == "cancelled" or job_cancelled:
                log_event(
                    ops_logging,
                    20,
                    "scan_item_skipped_cancelled",
                    job_id=request.job_id,
                    job_item_id=request.job_item_id,
                    object_identity=request.object_identity,
                )
                self._resolve_entry_future(entry, result="cancelled")
                return None
        reader = build_scan_reader(request, control_plane=self.service.control_plane)
        entry.scan_started_at = time.perf_counter()
        _log_scan_batch_item_event(
            20,
            "scan_batch_item_started",
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            integration_id=request.integration_id,
            scope_id=request.scope_id,
            object_identity=request.object_identity,
            content_source_mode=request.content_source.mode,
            reader=reader.__class__.__name__,
            scan_mode=settings.scanner.mode,
            active=self._active,
            pending=len(self._pending),
            completion_pending=len(self._completion_pending),
            elapsed_since_accept_ms=round((entry.scan_started_at - entry.accepted_at) * 1000.0, 3),
        )
        if use_runtime_lease:
            await _service_io(
                self.service_io_threaded,
                self.service.mark_scan_runtime_started,
                job_id=request.job_id,
                job_item_id=request.job_item_id,
            )
        try:
            try:
                result = await self.execute_scan(request, reader)
            except TerminalScanError as exc:
                log_event(
                    ops_logging,
                    30,
                    "scan_batch_item_terminal_failure",
                    job_id=request.job_id,
                    job_item_id=request.job_item_id,
                    object_identity=request.object_identity,
                    error=exc.as_error_payload(),
                )
                await _service_io(
                    self.service_io_threaded,
                    self.service.update_scan_stage,
                    request.job_item_id,
                    ScanStageUpdateRequest(state="failed", error=exc.as_error_payload()).as_stage_update_request(),
                )
                entry.scan_finished_at = time.perf_counter()
                self._resolve_entry_future(entry, result="terminal_scan_failure")
                return None
            entry.scan_finished_at = time.perf_counter()
            _log_scan_batch_item_event(
                20,
                "scan_only_batch_scan_finished",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
                verdict=result.verdict,
                verdict_details=result.verdict_details,
                scan_guid=result.scan_guid,
                file_type=result.file_type,
                active=self._active,
                pending=len(self._pending),
                completion_pending=len(self._completion_pending),
                scan_elapsed_ms=round((entry.scan_finished_at - entry.scan_started_at) * 1000.0, 3)
                if entry.scan_started_at is not None
                else None,
            )
            if not self.trust_items:
                current_item = await _service_io(self.service_io_threaded, self.service.get_job_item_or_404, request.job_item_id)
                job_cancelled = request.job_id in _CANCELLED_JOB_IDS or await _service_io(
                    self.service_io_threaded,
                    self.service.is_job_cancelled,
                    request.job_id,
                )
                if job_cancelled:
                    _CANCELLED_JOB_IDS.add(request.job_id)
                if current_item.state == "cancelled" or job_cancelled:
                    log_event(
                        ops_logging,
                        20,
                        "scan_batch_item_completion_discarded_cancelled",
                        job_id=request.job_id,
                        job_item_id=request.job_item_id,
                        object_identity=request.object_identity,
                    )
                    self._resolve_entry_future(entry, result="completion_discarded_cancelled")
                    return None
            scan_stage_request = ScanStageUpdateRequest(
                state="completed",
                scan_result=result,
                scanner_metadata=request.scan_options.get("_dsx_scanner_metadata") or {},
            ).as_stage_update_request()
            return request.job_id, request.job_item_id, scan_stage_request
        finally:
            if use_runtime_lease:
                await _service_io(self.service_io_threaded, self.service.clear_scan_runtime, job_item_id=request.job_item_id)

    async def _run_one(self, entry: ScanOnlyBatchEntry) -> None:
        try:
            result = await self._scan_one(entry)
        except Exception as exc:
            self._resolve_entry_future(entry, result="scan_exception", exc=exc)
            return
        finally:
            async with self._lock:
                self._active -= 1
                _log_scan_batch_item_event(
                    20,
                    "scan_only_batch_active_count_changed",
                    job_id=entry.request.job_id,
                    job_item_id=entry.request.job_item_id,
                    object_identity=entry.request.object_identity,
                    active=self._active,
                    pending=len(self._pending),
                    completion_pending=len(self._completion_pending),
                    scan_concurrency=self.scan_concurrency,
                    reason="scan_finished",
                )
                self._pump_locked()
        if result is None:
            self._resolve_entry_future(entry, result="no_completion_required")
            return
        async with self._lock:
            self._completion_pending.append((entry, result))
            if self.ack_mode == "scanned":
                self._resolve_entry_future(entry, result="scan_finished_completion_buffered")
            if len(self._completion_pending) >= self.batch_size:
                self._flush_requested = True
                self._ensure_completion_flush_task_locked()
            elif self._flush_timer is None or self._flush_timer.done():
                self._flush_timer = asyncio.create_task(self._flush_later())

    async def _flush_completions(self, completions: list[tuple[ScanOnlyBatchEntry, tuple[str, str, StageUpdateRequest]]]) -> None:
        started = time.perf_counter()
        updates = [update for _entry, update in completions]
        if updates:
            log_event(
                ops_logging,
                20,
                "scan_only_batch_completion_flush_started",
                attempted=len(updates),
                batch_size=self.batch_size,
                scan_concurrency=self.scan_concurrency,
            )
            try:
                completed = await _service_io(
                    self.service_io_threaded,
                    self.service.complete_scan_only_bulk,
                    updates,
                    refresh_parent=False,
                )
            except Exception as exc:
                for entry, _update in completions:
                    self._resolve_entry_future(entry, result="completion_flush_failed", exc=exc)
                log_event(
                    ops_logging,
                    40,
                    "scan_only_batch_completion_failed",
                    attempted=len(updates),
                    error={"code": "scan_only_batch_completion_failed", "message": str(exc)},
                )
                return
            for entry, _update in completions:
                self._resolve_entry_future(entry, result="completion_flushed")
            log_event(
                ops_logging,
                20,
                "scan_only_batch_completion_flush_finished",
                attempted=len(completions),
                completed=completed,
                elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
                batch_size=self.batch_size,
                scan_concurrency=self.scan_concurrency,
            )


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


def _dsxa_client_key() -> tuple[Any, ...]:
    return (
        settings.scanner.base_url.rstrip("/"),
        settings.scanner.dsxa_auth_token,
        settings.scanner.timeout_seconds,
        settings.scanner.verify_tls,
        settings.scanner.protected_entity,
    )


def get_dsxa_client():
    global _DSXA_CLIENT, _DSXA_CLIENT_KEY
    key = _dsxa_client_key()
    if _DSXA_CLIENT is not None and _DSXA_CLIENT_KEY == key:
        return _DSXA_CLIENT
    AsyncDSXAClient, *_ = _import_dsxa_client()
    _DSXA_CLIENT = AsyncDSXAClient(
        base_url=key[0],
        auth_token=key[1],
        timeout=key[2],
        verify_tls=key[3],
        default_protected_entity=key[4],
    )
    _DSXA_CLIENT_KEY = key
    return _DSXA_CLIENT


def new_dsxa_client():
    AsyncDSXAClient, *_ = _import_dsxa_client()
    key = _dsxa_client_key()
    return AsyncDSXAClient(
        base_url=key[0],
        auth_token=key[1],
        timeout=key[2],
        verify_tls=key[3],
        default_protected_entity=key[4],
    )


async def close_dsxa_client() -> None:
    global _DSXA_CLIENT, _DSXA_CLIENT_KEY
    client = _DSXA_CLIENT
    _DSXA_CLIENT = None
    _DSXA_CLIENT_KEY = None
    if client is not None:
        await client.aclose()


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


def _cleanup_owned_read_result(read_result) -> None:
    local_path = getattr(read_result, "local_path", None)
    if not getattr(read_result, "cleanup_local_path", False) or local_path is None:
        return
    try:
        Path(local_path).unlink(missing_ok=True)
    except OSError as exc:
        log_event(
            ops_logging,
            30,
            "reader_temp_artifact_cleanup_failed",
            path=str(local_path),
            error={"code": "cleanup_failed", "message": str(exc)},
        )


async def _iter_file_chunks(path: Path, *, chunk_size: int = 1024 * 1024):
    with path.open("rb") as source:
        while True:
            chunk = await asyncio.to_thread(source.read, chunk_size)
            if not chunk:
                break
            yield chunk


async def _timed_chunks(chunks: AsyncIterable[bytes], timing: StreamTiming) -> AsyncIterable[bytes]:
    iterator = chunks.__aiter__()
    while True:
        started = time.perf_counter()
        try:
            chunk = await iterator.__anext__()
        except StopAsyncIteration:
            timing.elapsed_ms += (time.perf_counter() - started) * 1000.0
            break
        timing.elapsed_ms += (time.perf_counter() - started) * 1000.0
        timing.bytes_read += len(chunk)
        timing.chunks += 1
        yield chunk


async def _timed_file_chunks(path: Path, timing: StreamTiming, *, chunk_size: int = 1024 * 1024) -> AsyncIterable[bytes]:
    with path.open("rb") as source:
        while True:
            started = time.perf_counter()
            chunk = await asyncio.to_thread(source.read, chunk_size)
            timing.elapsed_ms += (time.perf_counter() - started) * 1000.0
            if not chunk:
                break
            timing.bytes_read += len(chunk)
            timing.chunks += 1
            yield chunk


async def _scan_file_with_configured_transport(
    client,
    read_result,
    *,
    protected_entity: int | None,
    custom_metadata: str,
    password: str | None,
) -> tuple[Any, StreamTiming | None]:
    file_path = getattr(read_result, "local_path", None)
    if settings.scanner.transport == "by_path":
        if file_path is None:
            raise TerminalScanError(
                "reader_local_path_required",
                "scan_by_path transport requires a local reader path",
                details=getattr(read_result, "details", {}),
            )
        response = await client.scan_by_path(
            str(file_path),
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        if getattr(response, "verdict", None) == "Scanning":
            response = await client.poll_scan_by_path(
                response.scan_guid,
                interval_seconds=settings.scanner.by_path_poll_interval_seconds,
                timeout_seconds=settings.scanner.by_path_poll_timeout_seconds,
            )
        return response, None
    content_stream = getattr(read_result, "content_stream", None)
    stream_timing = StreamTiming()
    if content_stream is not None:
        response = await client.scan_binary_stream(
            _timed_chunks(content_stream, stream_timing),
            protected_entity=protected_entity,
            custom_metadata=custom_metadata,
            password=password,
        )
        return response, stream_timing
    if file_path is None:
        raise TerminalScanError(
            "reader_content_required",
            "binary stream transport requires a reader content stream or local path",
            details=getattr(read_result, "details", {}),
        )
    response = await client.scan_binary_stream(
        _timed_file_chunks(file_path, stream_timing),
        protected_entity=protected_entity,
        custom_metadata=custom_metadata,
        password=password,
    )
    return response, stream_timing


async def _scan_file_with_client_scope(
    read_result,
    *,
    protected_entity: int | None,
    custom_metadata: str,
    password: str | None,
) -> tuple[Any, StreamTiming | None]:
    if _SCANNER_CLIENT_SCOPE == "per-task":
        client = new_dsxa_client()
        try:
            return await _scan_file_with_configured_transport(
                client,
                read_result,
                protected_entity=protected_entity,
                custom_metadata=custom_metadata,
                password=password,
            )
        finally:
            await client.aclose()
    return await _scan_file_with_configured_transport(
        get_dsxa_client(),
        read_result,
        protected_entity=protected_entity,
        custom_metadata=custom_metadata,
        password=password,
    )


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
    read_result = None
    try:
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
        protected_entity = request.scan_options.get("protectedEntity") or request.scan_options.get("protected_entity")
        custom_metadata = build_scan_custom_metadata(
            request,
            reader_name=read_result.details.get("reader") or reader.__class__.__name__,
            reader_details=read_result.details,
        )
        password = request.scan_options.get("password")
        (
            _AsyncDSXAClient,
            _ScanResponse,
            DSXAError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            ServerError,
        ) = _import_dsxa_client()
        dsxa_started = time.perf_counter()
        try:
            response, stream_timing = await _scan_file_with_client_scope(
                read_result,
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
        proxy_response = read_result.details.get("proxyResponse")
        scanner_engine_elapsed_ms = (
            round(response.scan_duration_in_microseconds / 1000.0, 3)
            if getattr(response, "scan_duration_in_microseconds", None) is not None
            else None
        )
        response_wait_elapsed_ms = None
        if stream_timing is not None:
            response_wait_elapsed_ms = max(0.0, dsxa_elapsed_ms - stream_timing.elapsed_ms)
        request.scan_options["_dsx_scanner_metadata"] = {
            "source": "dsxa",
            "reader": read_result.details.get("reader"),
            "contentSourceMode": request.content_source.mode,
            "transport": settings.scanner.transport,
            "contentLength": read_result.content_length,
            "contentType": proxy_response.get("content_type") if isinstance(proxy_response, dict) else None,
            "readerElapsedMs": round(read_elapsed_ms, 3),
            "requestElapsedMs": getattr(response, "dsxconnect_request_elapsed_ms", None) or round(read_elapsed_ms + dsxa_elapsed_ms, 3),
            "streamReadElapsedMs": round(stream_timing.elapsed_ms, 3) if stream_timing is not None else None,
            "streamBytes": stream_timing.bytes_read if stream_timing is not None else None,
            "streamChunks": stream_timing.chunks if stream_timing is not None else None,
            "scannerResponseWaitElapsedMs": round(response_wait_elapsed_ms, 3) if response_wait_elapsed_ms is not None else None,
            "readElapsedMs": getattr(response, "dsxconnect_read_elapsed_ms", None),
            "scannerEngineElapsedMs": scanner_engine_elapsed_ms,
            "dsxaElapsedMs": getattr(response, "dsxconnect_dsxa_elapsed_ms", None) or round(dsxa_elapsed_ms, 3),
            "protectedEntity": result.protected_entity,
        }
        return result
    finally:
        if read_result is not None:
            _cleanup_owned_read_result(read_result)


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
    scan_only_completion_buffer: ScanOnlyCompletionBuffer | None = None,
    scan_only_runtime_leases: bool = True,
    service_io_threaded: bool = False,
) -> None:
    request = ScanItemRequested.from_envelope(envelope)
    scan_only = is_scan_only_request(request)
    coarse_durable_progress = uses_coarse_durable_scan_progress(request)
    if request.job_id in _CANCELLED_JOB_IDS:
        skipped_count = _CANCELLED_JOB_SKIP_COUNTS.get(request.job_id, 0) + 1
        _CANCELLED_JOB_SKIP_COUNTS[request.job_id] = skipped_count
        if skipped_count == 1 or skipped_count % 1000 == 0:
            log_event(
                ops_logging,
                20,
                "scan_item_skipped_cancelled_cached",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
                skipped_count=skipped_count,
            )
        return
    current_item = await _service_io(service_io_threaded, service.get_job_item_or_404, request.job_item_id)
    job_cancelled = await _service_io(service_io_threaded, service.is_job_cancelled, request.job_id)
    if job_cancelled:
        _CANCELLED_JOB_IDS.add(request.job_id)
        _CANCELLED_JOB_SKIP_COUNTS.setdefault(request.job_id, 0)
    if current_item.state == "cancelled" or job_cancelled:
        log_event(
            ops_logging,
            20,
            "scan_item_skipped_cancelled",
            job_id=request.job_id,
            job_item_id=request.job_item_id,
            object_identity=request.object_identity,
        )
        return
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
    if not coarse_durable_progress:
        await _service_io(
            service_io_threaded,
            service.update_scan_stage,
            request.job_item_id,
            ScanStageUpdateRequest(state="running").as_stage_update_request(),
        )
    use_runtime_lease = scan_only_runtime_leases or not scan_only or not coarse_durable_progress
    if use_runtime_lease:
        await _service_io(
            service_io_threaded,
            service.mark_scan_runtime_started,
            job_id=request.job_id,
            job_item_id=request.job_item_id,
        )
    try:
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
            await _service_io(
                service_io_threaded,
                service.update_scan_stage,
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
        current_item = await _service_io(service_io_threaded, service.get_job_item_or_404, request.job_item_id)
        job_cancelled = request.job_id in _CANCELLED_JOB_IDS or await _service_io(service_io_threaded, service.is_job_cancelled, request.job_id)
        if job_cancelled:
            _CANCELLED_JOB_IDS.add(request.job_id)
        if current_item.state == "cancelled" or job_cancelled:
            log_event(
                ops_logging,
                20,
                "scan_item_completion_discarded_cancelled",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
            )
            return
        scan_stage_request = ScanStageUpdateRequest(
            state="completed",
            scan_result=result,
            scanner_metadata=request.scan_options.get("_dsx_scanner_metadata") or {},
        ).as_stage_update_request()
        if scan_only and scan_only_completion_buffer is not None and coarse_durable_progress:
            await scan_only_completion_buffer.add(
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                payload=scan_stage_request,
            )
        elif scan_only:
            await _service_io(service_io_threaded, service.complete_scan_only, request.job_item_id, scan_stage_request)
        else:
            await service.complete_scan_and_request_policy(
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
            verdict_details=result.verdict_details,
            scan_guid=result.scan_guid,
            file_type=result.file_type,
            scanner_metadata=scan_stage_request.metadata,
        )
        if not scan_only:
            log_event(
                ops_logging,
                20,
                "policy_evaluation_requested",
                job_id=request.job_id,
                job_item_id=request.job_item_id,
                object_identity=request.object_identity,
            )
    finally:
        if use_runtime_lease:
            await _service_io(service_io_threaded, service.clear_scan_runtime, job_item_id=request.job_item_id)


async def mark_scan_message_failed_after_retries(
    service: JobService,
    envelope: MessageEnvelope,
    exc: Exception,
    headers: dict,
) -> None:
    request = ScanItemRequested.from_envelope(envelope)
    retry_attempt = headers.get("x-dsx-retry-attempt")
    if isinstance(exc, TerminalScanError):
        error = exc.as_error_payload()
    else:
        error = {
            "code": "scan_execution_failed",
            "message": str(exc),
            "retryable": True,
            "reason": "retry_attempts_exhausted",
            "retryAttempts": retry_attempt,
        }
    log_event(
        ops_logging,
        40,
        "scan_item_failed_after_retries",
        job_id=request.job_id,
        job_item_id=request.job_item_id,
        object_identity=request.object_identity,
        error=error,
    )
    service.update_scan_stage(
        request.job_item_id,
        ScanStageUpdateRequest(state="failed", error=error).as_stage_update_request(),
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
    parser.add_argument(
        "--scan-only-completion-batch-size",
        type=int,
        default=int(os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_BATCH_SIZE", "1")),
        help="Number of scan-only completions to buffer before bulk persistence.",
    )
    parser.add_argument(
        "--scan-only-completion-flush-interval-seconds",
        type=float,
        default=float(os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_FLUSH_INTERVAL_SECONDS", "1.0")),
        help="Maximum age for buffered scan-only completions before a bulk flush.",
    )
    parser.add_argument(
        "--scan-only-runtime-leases",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES", "true").lower() not in {"0", "false", "no", "off"},
        help="Record runtime scan leases for coarse scan-only batch work.",
    )
    parser.add_argument(
        "--scanner-client-scope",
        choices=["shared", "per-task"],
        default=os.environ.get("DSX_CONNECT_NG_LOCAL__SCANNER_CLIENT_SCOPE", "shared"),
        help="DSXA client lifetime used by the scan worker.",
    )
    parser.add_argument(
        "--service-io-threaded",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_WORKER_SERVICE_IO_THREADED", "false").lower()
        in {"1", "true", "yes", "on"},
        help="Run synchronous JobService calls in worker threads so scan task prefetch can overlap service I/O.",
    )
    parser.add_argument(
        "--scan-batch-window-size",
        type=int,
        default=int(os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE", "1")),
        help="Collect this many coarse scan-only messages and scan them as one async gather batch.",
    )
    parser.add_argument(
        "--scan-batch-window-wait-seconds",
        type=float,
        default=float(os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS", "0.05")),
        help="Maximum wait for a partial scan-only batch window before scanning it.",
    )
    parser.add_argument(
        "--scan-batch-concurrency",
        type=int,
        default=int(os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY", "0")),
        help="Maximum concurrent read/scan coroutines inside a scan-only batch window; 0 uses prefetch count.",
    )
    parser.add_argument(
        "--scan-batch-ack-mode",
        choices=["completed", "scanned", "accepted"],
        default=os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE", "completed"),
        help="When scan-only batch messages are acked: after terminal completion persistence, after scan completion buffering, or after worker pool acceptance.",
    )
    parser.add_argument(
        "--scan-batch-trust-items",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS", "true").lower()
        in {"1", "true", "yes", "on"},
        help="Skip per-item DB reads around scan-only pooled scans and trust the claimed message payload.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    global _SCANNER_CLIENT_SCOPE
    _SCANNER_CLIENT_SCOPE = args.scanner_client_scope
    service, summary = build_job_service()
    executor = resolve_scan_executor()
    executor_name = getattr(executor, "__name__", executor.__class__.__name__)
    completion_buffer = (
        ScanOnlyCompletionBuffer(
            service,
            batch_size=args.scan_only_completion_batch_size,
            flush_interval_seconds=args.scan_only_completion_flush_interval_seconds,
        )
        if args.scan_only_completion_batch_size > 1
        else None
    )
    batch_coordinator = (
        ScanOnlyBatchCoordinator(
            service,
            execute_scan=executor,
            batch_size=args.scan_batch_window_size,
            max_wait_seconds=args.scan_batch_window_wait_seconds,
            scan_concurrency=args.scan_batch_concurrency or args.prefetch_count,
            scan_only_runtime_leases=args.scan_only_runtime_leases,
            service_io_threaded=args.service_io_threaded,
            ack_mode=args.scan_batch_ack_mode,
            trust_items=args.scan_batch_trust_items,
        )
        if args.scan_batch_window_size > 1
        else None
    )
    print(
        json.dumps(
            {
                "event": "scan_worker_start",
                **summary,
                "queue": args.queue,
                "scan_executor": executor_name,
                "default_reader_strategy": settings.readers.default_strategy,
                "scan_only_completion_batch_size": args.scan_only_completion_batch_size,
                "scan_only_runtime_leases": args.scan_only_runtime_leases,
                "scanner_client_scope": args.scanner_client_scope,
                "service_io_threaded": args.service_io_threaded,
                "scan_batch_window_size": args.scan_batch_window_size,
                "scan_batch_window_wait_seconds": args.scan_batch_window_wait_seconds,
                "scan_batch_concurrency": args.scan_batch_concurrency or args.prefetch_count,
                "scan_batch_ack_mode": args.scan_batch_ack_mode,
                "scan_batch_trust_items": args.scan_batch_trust_items,
            }
        ),
        flush=True,
    )

    async def flush_completion_buffer_forever() -> None:
        if completion_buffer is None:
            return
        while True:
            await asyncio.sleep(args.scan_only_completion_flush_interval_seconds)
            await completion_buffer.flush_due()

    async def handle(envelope: MessageEnvelope) -> None:
        if batch_coordinator is not None:
            request = ScanItemRequested.from_envelope(envelope)
            if is_scan_only_request(request) and uses_coarse_durable_scan_progress(request):
                await batch_coordinator.add(envelope)
                return
        await process_scan_message(
            service,
            envelope,
            execute_scan=executor,
            scan_only_completion_buffer=completion_buffer,
            scan_only_runtime_leases=args.scan_only_runtime_leases,
            service_io_threaded=args.service_io_threaded,
        )

    async def handle_terminal_failure(envelope: MessageEnvelope, exc: Exception, headers: dict) -> None:
        await mark_scan_message_failed_after_retries(service, envelope, exc, headers)

    flush_task = asyncio.create_task(flush_completion_buffer_forever()) if completion_buffer is not None else None
    try:
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
            terminal_failure_handler=handle_terminal_failure,
        )
    finally:
        if flush_task is not None:
            flush_task.cancel()
            await asyncio.gather(flush_task, return_exceptions=True)
        if completion_buffer is not None:
            await completion_buffer.flush_all()
        if batch_coordinator is not None:
            await batch_coordinator.flush_all()
        await close_dsxa_client()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
