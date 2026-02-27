# … existing imports …
import io
import time
import urllib.parse
import random
import sys
from pathlib import Path

import httpx
from celery import states
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from dsx_connect.dsxa_sdk_import import ensure_sdk_on_path

ensure_sdk_on_path()

from dsxa_sdk import DSXAClient
from dsxa_sdk.exceptions import DSXAError, AuthenticationError, BadRequestError, ServerError
from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryDecision, RetryGroups
from dsx_connect.config import get_config
from dsx_connect.taskworkers.dlq_store import enqueue_scan_request_dlq_sync, make_scan_request_dlq_item

from dsx_connect.connectors.client import get_connector_client
from shared.models.connector_models import ScanRequestModel
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.errors import MalformedScanRequest, DsxaClientError, DsxaServerError, DsxaTimeoutError, \
    DsxaAuthError, ConnectorClientError, ConnectorServerError, ConnectorConnectionError
from dsx_connect.taskworkers.names import Tasks, Queues
import redis  # lightweight sync client for quick job-state checks
from shared.dsx_logging import dsx_logging
from shared.routes import ConnectorAPI
from dsx_connect.dsxa_client.verdict_models import (
    DPAVerdictModel2,
    DPAVerdictEnum,
    DPAVerdictDetailsModel,
    DPAVerdictFileInfoModel,
)
from dsx_connect.messaging.state_keys import job_key, scanner_inflight_key
from dsx_connect.messaging.state_scripts import get_acquire_scanner_script

class ScanRequestWorker(BaseWorker):
    """
    Celery task to process incoming scan requests.
    Validates the request, fetches the file, scans it via DSXA, and dispatches a
    verdict task. Error handling, retries, and DLQ submission are delegated to
    BaseWorker.
    """
    name = Tasks.REQUEST
    RETRY_GROUPS = RetryGroups.connector_and_dsxa()
    _dsxa_auth_failed = False
    _dsxa_auth_log_emitted = False
    _redis = None

    def execute(self, scan_request_dict: dict, *, scan_request_task_id: str = None) -> str:
        # 1. Validate input (convert Pydantic errors to our domain error)
        try:
            scan_request = ScanRequestModel.model_validate(scan_request_dict)
        except ValidationError as e:
            raise MalformedScanRequest(f"Invalid scan request: {e}") from e

        if self.__class__._dsxa_auth_failed:
            if not self.__class__._dsxa_auth_log_emitted:
                dsx_logging.error(
                    "[scan_request] DSXA auth is failing; scanner AUTH_TOKEN is missing or incorrect. "
                    "Tasks will be sent to DLQ until DSXCONNECT_SCANNER__AUTH_TOKEN is fixed and workers restarted."
                )
                self.__class__._dsxa_auth_log_emitted = True
            raise DsxaAuthError(
                "DSXA auth failure: incorrect or missing AUTH_TOKEN/DSXCONNECT_SCANNER__AUTH_TOKEN"
            )

        # Record per-job scan start timestamps (best-effort)
        try:
            job_id = getattr(scan_request, "scan_job_id", None)
            if job_id:
                r = self.__class__._redis
                if r is None:
                    self.__class__._redis = redis.from_url(str(cfg.redis_url), decode_responses=True)
                    r = self.__class__._redis
                now = str(int(time.time()))
                key = job_key(job_id)
                r.hsetnx(key, "job_id", job_id)
                r.hsetnx(key, "status", "running")
                r.hsetnx(key, "first_scan_started_at", now)
                r.hset(key, mapping={"last_scan_started_at": now, "last_update": now})
                r.expire(key, 7 * 24 * 3600)
        except Exception:
            pass

        dsx_logging.info(f"[scan_request:{self.request.id}] for {scan_request.metainfo} started")

        # 1a. Respect job pause/cancel (best-effort): quick sync Redis check
        cfg = get_config()
        job_id = getattr(scan_request, "scan_job_id", None)
        if job_id:
            try:
                r = redis.Redis.from_url(str(cfg.redis_url), decode_responses=True)
                key = job_key(job_id)
                paused, cancelled = r.hmget(key, "paused", "cancel")
            except redis.RedisError:
                paused = cancelled = None
            # Act on flags if present
            if cancelled == "1":
                dsx_logging.info(f"[scan_request:{self.request.id}] Job {job_id} cancelled; dropping task")
                return "CANCELLED"
            if paused == "1":
                # Reschedule without consuming Celery retry budget.
                # We enqueue an identical task with a short delay and return.
                try:
                    import random
                    delay = 5 + random.randint(0, 5)  # small jitter to avoid herd on resume
                    async_result = celery_app.send_task(
                        Tasks.REQUEST,
                        args=[scan_request_dict],
                        kwargs={"scan_request_task_id": scan_request_task_id or self.request.id},
                        queue=Queues.REQUEST,
                        countdown=delay,
                    )
                    dsx_logging.info(
                        f"[scan_request:{self.request.id}] Job {job_id} paused; rescheduled as {async_result.id} in {delay}s"
                    )
                except Exception as e:
                    # If re-enqueue fails, fall back to a light retry (once) without blowing up the task
                    dsx_logging.warning(
                        f"[scan_request:{self.request.id}] Pause re-enqueue failed: {e}; backing off 5s"
                    )
                    raise self.retry(countdown=5)
                return "PAUSED"

        request_start = time.perf_counter()

        # 1b. Preflight skip for oversized files (based on provided size hint, if any)
        size_hint = getattr(scan_request, "size_in_bytes", None)
        max_file_size = getattr(cfg.scanner, "max_file_size_bytes", None)
        if max_file_size and size_hint is not None and size_hint > max_file_size:
            dsx_logging.warning(
                f"[scan_request:{getattr(self.context, 'task_id', 'unknown')}] "
                f"Skipping {scan_request.location} (hint size {size_hint} bytes exceeds limit {max_file_size})"
            )
            self._emit_not_scanned_verdict(
                scan_request_dict,
                scan_request,
                size_hint,
                reason="File Size Too Large",
                request_elapsed_ms=(time.perf_counter() - request_start) * 1000.0,
            )
            return "SKIPPED_FILE_TOO_LARGE"

        slot_acquired = False
        # 2. Read file from connector
        try:
            slot_acquired = self._acquire_scanner_slot(cfg, scan_request_dict, scan_request_task_id)
            if not slot_acquired:
                return "BACKPRESSURE"

            file_stream, stream_size = self.read_file_stream_from_connector(scan_request)
            if stream_size is not None:
                dsx_logging.debug(f"[scan_request:{self.context.task_id}] Read stream ({stream_size} bytes)")
            else:
                dsx_logging.debug(f"[scan_request:{self.context.task_id}] Read stream (size unknown)")

            if max_file_size and stream_size is not None and stream_size > max_file_size:
                dsx_logging.warning(
                    f"[scan_request:{getattr(self.context, 'task_id', 'unknown')}] "
                    f"Skipping {scan_request.location} (actual size {stream_size} bytes exceeds limit {max_file_size})"
                )
                size_for_verdict = stream_size if stream_size is not None else (size_hint or 0)
                self._emit_not_scanned_verdict(
                    scan_request_dict,
                    scan_request,
                    size_for_verdict,
                    reason="File Size Too Large",
                    request_elapsed_ms=(time.perf_counter() - request_start) * 1000.0,
                )
                return "SKIPPED_FILE_TOO_LARGE"

            # 3. Scan with DSXA
            dpa_verdict = self.scan_with_dsxa_stream(file_stream, scan_request, self.context.task_id)
            request_elapsed_ms = (time.perf_counter() - request_start) * 1000.0
            try:
                dpa_verdict = dpa_verdict.model_copy(
                    update={"dsxconnect_request_elapsed_ms": request_elapsed_ms}
                )
            except Exception:
                try:
                    dpa_verdict.dsxconnect_request_elapsed_ms = request_elapsed_ms
                except Exception:
                    pass
            dsx_logging.debug(
                f"[scan_request:{self.context.task_id}] Verdict: {getattr(dpa_verdict, 'verdict', None)}"
            )

            # 4. Enqueue verdict task
            verdict_payload = dpa_verdict.model_dump() if hasattr(dpa_verdict, "model_dump") else dpa_verdict
            async_result = celery_app.send_task(
                Tasks.VERDICT,
                args=[scan_request_dict, verdict_payload],
                kwargs={"scan_request_task_id": self.request.id},
                queue=Queues.VERDICT,
            )
            dsx_logging.info(
                f"[scan_request:{self.context.task_id}] Success -> verdict task {async_result.id}"
            )
            return "SUCCESS"
        finally:
            if slot_acquired:
                self._release_scanner_slot(cfg)


    def read_file_stream_from_connector(self, scan_request: ScanRequestModel):
        """Read file bytes as a stream from connector. Maps exceptions to task-appropriate errors."""
        target = scan_request.connector or scan_request.connector_url
        try:
            with get_connector_client(target) as client:
                response = client.post(
                    ConnectorAPI.READ_FILE,
                    json_body=jsonable_encoder(scan_request),
                )
            response.raise_for_status()
            try:
                content_length = response.headers.get("content-length")
                size = int(content_length) if content_length else None
            except Exception:
                size = None
            if size is None:
                size = getattr(scan_request, "size_in_bytes", None)

            def iter_chunks():
                try:
                    for chunk in response.iter_bytes():
                        if chunk:
                            yield chunk
                finally:
                    response.close()

            return iter_chunks(), size

        except httpx.ConnectError as e:
            if "Name does not resolve" in str(e) or "Connection refused" in str(e):
                raise ConnectorConnectionError(f"Connector unavailable: {e}") from e
            raise ConnectorConnectionError(f"Connector connection failed: {e}") from e

        except httpx.HTTPStatusError as e:
            if 500 <= e.response.status_code < 600:
                raise ConnectorServerError(f"Connector server error {e.response.status_code}") from e
            elif 400 <= e.response.status_code < 500:
                raise ConnectorClientError(f"Connector client error {e.response.status_code}") from e
            raise ConnectorConnectionError(f"Connector HTTP error {e.response.status_code}") from e


    def scan_with_dsxa_stream(self, file_stream, scan_request: ScanRequestModel, task_id: str = None):
        """Scan file with DSXA via dsxa_sdk using a streaming payload."""
        config = get_config()
        metadata_info = self._build_metadata(scan_request, task_id)

        client = DSXAClient(
            base_url=config.scanner.base_url,
            auth_token=getattr(config.scanner, "auth_token", None),
            timeout=getattr(config.scanner, "timeout_seconds", 30.0),
            verify_tls=getattr(config.scanner, "verify_tls", True),
        )

        try:
            resp = client.scan_binary_stream(
                file_stream,
                custom_metadata=metadata_info,
            )
            dpa_verdict = self._convert_verdict(resp)

            # Handle special "initializing" case
            reason = getattr(dpa_verdict.verdict_details, "reason", "") or ""
            if dpa_verdict.verdict == DPAVerdictEnum.NOT_SCANNED and "initializing" in reason:
                raise DsxaServerError("DSXA scanner is initializing")

            return dpa_verdict

        except DSXAError as e:
            # Map SDK errors to our taxonomy
            if isinstance(e, AuthenticationError):
                self.__class__._dsxa_auth_failed = True
                if not self.__class__._dsxa_auth_log_emitted:
                    dsx_logging.error(
                        "DSXA auth failed (401/403). Verify AUTH_TOKEN on the scanner and "
                        "DSXCONNECT_SCANNER__AUTH_TOKEN in dsx-connect. "
                        "Tasks will be sent to DLQ until fixed."
                    )
                    self.__class__._dsxa_auth_log_emitted = True
                raise DsxaAuthError(
                    "DSXA auth error: incorrect or missing AUTH_TOKEN/DSXCONNECT_SCANNER__AUTH_TOKEN"
                ) from e
            if isinstance(e, BadRequestError):
                raise DsxaClientError(f"DSXA bad request: {e}") from e
            if isinstance(e, ServerError):
                raise DsxaServerError(f"DSXA server error: {e}") from e
            if "timeout" in str(e).lower():
                raise DsxaTimeoutError(f"DSXA timeout: {e}") from e
            raise DsxaServerError(f"DSXA error: {e}") from e
        except httpx.TimeoutException as e:
            raise DsxaTimeoutError(f"DSXA timeout: {e}") from e
        except httpx.HTTPError as e:
            raise DsxaServerError(f"DSXA connection error: {e}") from e
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _build_metadata(self, scan_request: ScanRequestModel, task_id: str | None) -> str:
        def _encode_value(value: str) -> str:
            if not value:
                return ""
            try:
                value.encode("ascii")
                return value
            except UnicodeEncodeError:
                return urllib.parse.quote(value, safe="")

        safe_meta = _encode_value(scan_request.metainfo or "")
        file_path = _encode_value(str(scan_request.location or ""))
        connector_name = None
        try:
            connector_name = getattr(getattr(scan_request, "connector", None), "name", None)
        except Exception:
            connector_name = None
        if not connector_name:
            connector_name = getattr(scan_request, "connector_name", None)
        connector_name = _encode_value(connector_name or "")
        if connector_name:
            metadata_info = f"file-loc:{file_path},file-meta:{safe_meta},dsx-connect:{connector_name}"
        else:
            metadata_info = f"file-loc:{file_path},file-meta:{safe_meta}"
        if task_id:
            metadata_info += f",scan_request_task_id:{_encode_value(task_id)}"
        return metadata_info

    def _convert_verdict(self, resp):
        # Map dsxa_sdk ScanResponse to DPAVerdictModel2 (legacy)
        verdict_map = {
            "benign": DPAVerdictEnum.BENIGN,
            "malicious": DPAVerdictEnum.MALICIOUS,
            "not scanned": DPAVerdictEnum.NOT_SCANNED,
            "scanning": DPAVerdictEnum.NOT_SCANNED,
            "non compliant": DPAVerdictEnum.NON_COMPLIANT,
            "unknown": DPAVerdictEnum.UNKNOWN,
        }
        raw_verdict = getattr(resp, "verdict", None)
        verdict_str = raw_verdict.value if hasattr(raw_verdict, "value") else str(raw_verdict or "")
        verdict_val = verdict_map.get(verdict_str.lower(), DPAVerdictEnum.UNKNOWN)

        details = DPAVerdictDetailsModel(
            event_description=getattr(resp.verdict_details, "event_description", None) or "",
            reason=getattr(resp.verdict_details, "reason", None),
            threat_type=getattr(resp.verdict_details, "threat_type", None),
        )

        file_info = None
        if resp.file_info:
            file_info = DPAVerdictFileInfoModel(
                file_type=getattr(resp.file_info, "file_type", None) or "",
                file_size_in_bytes=getattr(resp.file_info, "file_size_in_bytes", None) or 0,
                file_hash=getattr(resp.file_info, "file_hash", None),
                container_hash=getattr(resp.file_info, "container_hash", None),
                additional_office_data=None,
            )

        return DPAVerdictModel2(
            scan_guid=getattr(resp, "scan_guid", None),
            verdict=verdict_val,
            verdict_details=details,
            file_info=file_info,
            protected_entity=getattr(resp, "protected_entity", None),
            scan_duration_in_microseconds=getattr(resp, "scan_duration_in_microseconds", None) or -1,
            container_files_scanned=getattr(resp, "container_files_scanned", None),
            container_files_scanned_size=getattr(resp, "container_files_scanned_size", None),
            x_custom_metadata=getattr(resp, "x_custom_metadata", None),
            last_update_time=getattr(resp, "last_update_time", None),
        )

    def _enqueue_dlq(
            self,
            *,
            error: Exception,
            reason: str,
            scan_request_task_id: str,
            current_task_id: str,
            retry_count: int,
            upstream_task_id: str | None = None,
            args: tuple,
            kwargs: dict,
    ) -> None:
        # args: [scan_request_dict]
        scan_request_dict = args[0] if len(args) > 0 else {}

        item = make_scan_request_dlq_item(
            scan_request=scan_request_dict,
            error=error,
            reason=reason,
            scan_request_task_id=scan_request_task_id,  # root (will equal current for the root task)
            current_task_id=current_task_id,
            retry_count=retry_count,
            upstream_task_id=upstream_task_id,
        )
        enqueue_scan_request_dlq_sync(item)

    def _acquire_scanner_slot(self, cfg, scan_request_dict: dict, scan_request_task_id: str | None) -> bool:
        """Simple backpressure: cap concurrent/pending scans to protect DSXA."""
        max_inflight = getattr(cfg.scanner, "max_inflight", 0) or 0
        if max_inflight <= 0:
            return True

        try:
            r = redis.Redis.from_url(str(cfg.redis_url), decode_responses=True)
            key = scanner_inflight_key()
            ttl_seconds = 600
            script = get_acquire_scanner_script(r)
            result = script(keys=[key], args=[max_inflight, ttl_seconds])
            acquired = False
            inflight = None
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                acquired = bool(result[0])
                inflight = int(result[1])
            else:
                acquired = bool(result)
            if not acquired:
                delay = 3 + random.randint(0, 3)
                async_result = celery_app.send_task(
                    Tasks.REQUEST,
                    args=[scan_request_dict],
                    kwargs={"scan_request_task_id": scan_request_task_id or getattr(self.request, "id", None)},
                    queue=Queues.REQUEST,
                    countdown=delay,
                )
                inflight_desc = f"{inflight}" if inflight is not None else "unknown"
                dsx_logging.warning(
                    f"[scan_request:{getattr(self.context, 'task_id', 'unknown')}] "
                    f"Scanner at capacity ({inflight_desc}/{max_inflight}); "
                    f"rescheduled as {async_result.id} in {delay}s"
                )
                return False
            return True
        except redis.RedisError as e:
            dsx_logging.warning(
                f"[scan_request:{getattr(self.context, 'task_id', 'unknown')}] "
                f"Backpressure check skipped (Redis error): {e}"
            )
            return True

    def _release_scanner_slot(self, cfg) -> None:
        max_inflight = getattr(cfg.scanner, "max_inflight", 0) or 0
        if max_inflight <= 0:
            return
        try:
            r = redis.Redis.from_url(str(cfg.redis_url), decode_responses=True)
            r.decr(scanner_inflight_key())
        except redis.RedisError:
            # Best-effort; if Redis is unavailable, counters may drift until service restarts
            pass

    def _emit_not_scanned_verdict(
        self,
        scan_request_dict: dict,
        scan_request: ScanRequestModel,
        size: int,
        reason: str,
        request_elapsed_ms: float | None = None,
    ):
        """Emit a synthetic Not Scanned verdict so downstream logging/UI can act on oversized files."""
        details = DPAVerdictDetailsModel(
            event_description="File not scanned",
            reason=reason,
        )
        file_info = DPAVerdictFileInfoModel(
            file_type="Unknown",
            file_size_in_bytes=size,
            file_hash="",
            additional_office_data=None,
        )
        # DSXA returns GUID-like strings without dashes; mimic that for consistency
        from uuid import uuid4
        synthetic_guid = uuid4().hex

        verdict = DPAVerdictModel2(
            scan_guid=synthetic_guid,
            verdict=DPAVerdictEnum.NON_COMPLIANT,
            verdict_details=details,
            file_info=file_info,
            scan_duration_in_microseconds=0,
            dsxconnect_request_elapsed_ms=request_elapsed_ms,
        )
        verdict_payload = verdict.model_dump()
        async_result = celery_app.send_task(
            Tasks.VERDICT,
            args=[scan_request_dict, verdict_payload],
            kwargs={"scan_request_task_id": getattr(self.request, "id", None)},
            queue=Queues.VERDICT,
        )
        dsx_logging.info(
            f"[scan_request:{getattr(self.context, 'task_id', 'unknown')}] "
            f"Emitted Not Scanned verdict for oversized file (size={size}); verdict task {async_result.id}"
        )

# Register the class-based task with Celery
celery_app.register_task(ScanRequestWorker())
