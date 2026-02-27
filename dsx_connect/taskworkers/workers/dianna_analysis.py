import base64
import hashlib
import time
from typing import Any, Dict, Optional

import httpx
from fastapi.encoders import jsonable_encoder

from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryGroups
from dsx_connect.taskworkers.errors import (
    ConnectorClientError, ConnectorConnectionError, ConnectorServerError,
)
from dsx_connect.taskworkers.names import Tasks, Queues
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.config import get_config
from dsx_connect.connectors.client import get_connector_client
from shared.models.connector_models import ScanRequestModel
from shared.dsx_logging import dsx_logging
from shared.routes import ConnectorAPI
from shared.log_chain import syslog_logger


class DiannaAnalysisWorker(BaseWorker):
    name = Tasks.DIANNA_ANALYZE
    RETRY_GROUPS = RetryGroups.connector()  # network to DI may be treated as connector-like

    @staticmethod
    def _result_payload(
            *,
            status: str,
            analysis_id: str | int | None = None,
            upload_id: str | None = None,
            response: Dict[str, Any] | None = None,
            message: str | None = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"status": status}
        if analysis_id is not None and str(analysis_id).strip():
            payload["analysis_id"] = str(analysis_id)
        if upload_id:
            payload["upload_id"] = upload_id
        if response is not None:
            payload["response"] = response
        if message:
            payload["message"] = message
        return payload

    def execute(self, scan_request_dict: dict, *, archive_password: str | None = None,
                scan_request_task_id: str | None = None) -> str:
        # Validate minimal scan request using existing model
        scan_req = ScanRequestModel.model_validate(scan_request_dict)

        cfg = get_config().dianna
        chunk_size = int(cfg.chunk_size)
        file_stream, total_size = self._read_file_stream_from_connector(scan_req, chunk_size)
        if total_size is None:
            file_bytes = self._read_file_from_connector(scan_req)
            total_size = len(file_bytes)
            file_stream = (file_bytes[i:i + chunk_size] for i in range(0, total_size, chunk_size))

        # Upload to DIANNA
        url = cfg.management_url.rstrip('/') + '/api/v1/dianna/analyzeFile'
        headers = {"Authorization": f"{cfg.api_token}"} if cfg.api_token else {}
        timeout = httpx.Timeout(cfg.timeout)

        resp_json: Optional[Dict[str, Any]] = None
        upload_id: Optional[str] = None
        sha256: Optional[str] = None

        analysis_result: Optional[Dict[str, Any]] = None
        try:
            with httpx.Client(timeout=timeout, verify=(cfg.ca_bundle or cfg.verify_tls)) as client:
                hasher = hashlib.sha256()
                offset = 0
                upload_status: Optional[str] = None
                for chunk in file_stream:
                    if not chunk:
                        continue
                    hasher.update(chunk)
                    payload = {
                        'start_byte': offset,
                        'end_byte': offset + len(chunk) - 1,
                        'total_bytes': total_size,
                        'upload_id': upload_id,
                        'file_name': scan_req.metainfo or scan_req.location,
                        'file_chunk': base64.b64encode(chunk).decode('utf-8'),
                    }
                    if archive_password:
                        payload['archive_password'] = archive_password
                    r = client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    resp_json = r.json() if r.content else {}
                    upload_id = (resp_json or {}).get('upload_id') or upload_id
                    upload_status = str((resp_json or {}).get("status", "")).upper() or upload_status
                    offset += len(chunk)
                sha256 = hasher.hexdigest()

                if upload_status in {"FAILED", "ERROR", "CANCELLED", "UNSUPPORTED_FILE_TYPE"}:
                    msg = (
                        f"DIANNA upload returned terminal status {upload_status} "
                        f"(analysisId={(resp_json or {}).get('analysisId')}, upload_id={upload_id})"
                    )
                    dsx_logging.warning(f"[dianna:{self.context.task_id}] {msg}")
                    try:
                        from dsx_connect.messaging.bus import SyncBus
                        from dsx_connect.messaging.notifiers import Notifiers
                        from dsx_connect.config import get_config as _gc
                        bus = SyncBus(str(_gc().redis_url))
                        notifier = Notifiers(bus)
                        ui_event = {
                            "type": "dianna_analysis",
                            "status": upload_status,
                            "location": scan_req.location,
                            "connector_url": scan_req.connector_url,
                            "sha256": sha256,
                            "upload_id": upload_id,
                            "analysis": resp_json or {},
                            "error": msg,
                        }
                        notifier.publish_scan_results_sync(ui_event)
                    except Exception:
                        pass
                    return self._result_payload(status="ERROR", upload_id=upload_id, response=resp_json, message=msg)

                analysis_id = (resp_json or {}).get("analysisId")
                if not upload_id and analysis_id is not None:
                    immediate_result: Dict[str, Any] | None = None
                    if cfg.poll_results_enabled:
                        try:
                            poll_url = cfg.management_url.rstrip('/') + f"/api/v1/dianna/analysisResult/{analysis_id}"
                            deadline = time.time() + int(cfg.poll_timeout_seconds)
                            interval = max(1, int(cfg.poll_interval_seconds))
                            while time.time() < deadline:
                                gr = client.get(poll_url, headers={**headers, "accept": "application/json"})
                                if gr.status_code == 200:
                                    immediate_result = gr.json() if gr.content else {}
                                    status = str((immediate_result or {}).get("status", "")).upper()
                                    if status in {"SUCCESS", "FAILED", "ERROR", "CANCELLED", "UNSUPPORTED_FILE_TYPE"}:
                                        break
                                time.sleep(interval)
                        except Exception as e:
                            dsx_logging.warning(
                                f"[dianna:{self.context.task_id}] analysisResult lookup failed for {analysis_id}: {e}"
                            )

                    dsx_logging.info(
                        f"[dianna:{self.context.task_id}] analysis completed immediately for {scan_req.location} "
                        f"(analysisId={analysis_id})"
                    )
                    final_analysis = immediate_result or resp_json or {}
                    final_status = str((final_analysis or {}).get("status", "SUCCESS")).upper() or "SUCCESS"
                    try:
                        from dsx_connect.messaging.bus import SyncBus
                        from dsx_connect.messaging.notifiers import Notifiers
                        from dsx_connect.config import get_config as _gc
                        bus = SyncBus(str(_gc().redis_url))
                        notifier = Notifiers(bus)
                        ui_event = {
                            "type": "dianna_analysis",
                            "status": final_status,
                            "location": scan_req.location,
                            "connector_url": scan_req.connector_url,
                            "sha256": sha256,
                            "upload_id": upload_id,
                            "analysis": final_analysis,
                            "is_malicious": bool((final_analysis or {}).get("isFileMalicious", False)),
                        }
                        notifier.publish_scan_results_sync(ui_event)
                    except Exception:
                        pass
                    try:
                        from json import dumps
                        syslog_logger.info(dumps({
                            "event": "dianna_analysis",
                            "location": scan_req.location,
                            "connector_url": scan_req.connector_url,
                            "sha256": sha256,
                            "upload_id": upload_id,
                            "phase": "RESULT",
                            "analysis": final_analysis,
                        }))
                    except Exception:
                        pass
                    if final_status in {"FAILED", "ERROR", "CANCELLED", "UNSUPPORTED_FILE_TYPE"}:
                        return self._result_payload(
                            status=final_status,
                            analysis_id=analysis_id,
                            upload_id=upload_id,
                            response=final_analysis,
                            message="DIANNA returned terminal failure status",
                        )
                    return self._result_payload(
                        status=final_status or "SUCCESS",
                        analysis_id=analysis_id,
                        upload_id=upload_id,
                        response=final_analysis,
                    )

                # Initial notify: upload completed, analysis queued
                try:
                    from dsx_connect.messaging.bus import SyncBus
                    from dsx_connect.messaging.notifiers import Notifiers
                    from dsx_connect.config import get_config as _gc
                    bus = SyncBus(str(_gc().redis_url))
                    notifier = Notifiers(bus)
                    ui_event = {
                        "type": "dianna_analysis",
                        "status": str(upload_status or "QUEUED"),
                        "location": scan_req.location,
                        "connector_url": scan_req.connector_url,
                        "sha256": sha256,
                        "upload_id": upload_id,
                    }
                    notifier.publish_scan_results_sync(ui_event)
                except Exception:
                    pass

                # Poll for analysis result if enabled and we have an upload_id
                if cfg.poll_results_enabled and upload_id:
                    poll_url = cfg.management_url.rstrip('/') + f"/api/v1/dianna/analysisResult/{upload_id}"
                    deadline = time.time() + int(cfg.poll_timeout_seconds)
                    interval = max(1, int(cfg.poll_interval_seconds))
                    last_status: Optional[str] = None
                    while time.time() < deadline:
                        try:
                            gr = client.get(poll_url, headers={**headers, "accept": "application/json"})
                            if gr.status_code == 200:
                                analysis_result = gr.json() if gr.content else {}
                                status = str((analysis_result or {}).get("status", "")).upper()
                                last_status = status or last_status
                                if status in {"SUCCESS", "FAILED", "ERROR", "CANCELLED", "UNSUPPORTED_FILE_TYPE"}:
                                    break
                            # Non-200: treat as transient and keep polling
                        except Exception:
                            # Swallow transient errors and continue polling until timeout
                            pass
                        time.sleep(interval)

                # Final notify if we have a terminal result
                if upload_id and analysis_result:
                    try:
                        from dsx_connect.messaging.bus import SyncBus
                        from dsx_connect.messaging.notifiers import Notifiers
                        from dsx_connect.config import get_config as _gc
                        bus = SyncBus(str(_gc().redis_url))
                        notifier = Notifiers(bus)
                        status = str((analysis_result or {}).get("status", "")).upper() or "SUCCESS"
                        ui_event = {
                            "type": "dianna_analysis",
                            "status": status,
                            "location": scan_req.location,
                            "connector_url": scan_req.connector_url,
                            "sha256": sha256,
                            "upload_id": upload_id,
                            "analysis": analysis_result,
                            "is_malicious": bool((analysis_result or {}).get("isFileMalicious", False)),
                        }
                        notifier.publish_scan_results_sync(ui_event)
                    except Exception:
                        pass

                terminal_status = str((analysis_result or {}).get("status", "")).upper() if analysis_result else None
                if terminal_status in {"FAILED", "ERROR", "CANCELLED", "UNSUPPORTED_FILE_TYPE"}:
                    dsx_logging.warning(
                        f"[dianna:{self.context.task_id}] analysis failed for {scan_req.location} "
                        f"(status={terminal_status}, upload_id={upload_id})"
                    )
                    return self._result_payload(
                        status=terminal_status,
                        upload_id=upload_id,
                        response=analysis_result,
                        message="DIANNA returned terminal failure status",
                    )
        except httpx.HTTPStatusError as e:
            code = getattr(e.response, 'status_code', 'unknown')
            msg = f"HTTP {code}: {e}"
            dsx_logging.warning(f"[dianna:{self.context.task_id}] DIANNA HTTP status error {code}: {e}")
            # Notify UI about failure
            try:
                from dsx_connect.messaging.bus import SyncBus
                from dsx_connect.messaging.notifiers import Notifiers
                from dsx_connect.config import get_config as _gc
                bus = SyncBus(str(_gc().redis_url))
                notifier = Notifiers(bus)
                ui_event = {
                    "type": "dianna_analysis",
                    "status": "ERROR",
                    "location": scan_req.location,
                    "connector_url": scan_req.connector_url,
                    "sha256": sha256,
                    "upload_id": upload_id,
                    "error": msg,
                }
                notifier.publish_scan_results_sync(ui_event)
            except Exception:
                pass
            return self._result_payload(status="ERROR", upload_id=upload_id, response=resp_json, message=msg)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            msg = f"connection: {e}"
            dsx_logging.warning(f"[dianna:{self.context.task_id}] DIANNA connection error: {e}")
            try:
                from dsx_connect.messaging.bus import SyncBus
                from dsx_connect.messaging.notifiers import Notifiers
                from dsx_connect.config import get_config as _gc
                bus = SyncBus(str(_gc().redis_url))
                notifier = Notifiers(bus)
                ui_event = {
                    "type": "dianna_analysis",
                    "status": "ERROR",
                    "location": scan_req.location,
                    "connector_url": scan_req.connector_url,
                    "sha256": sha256,
                    "upload_id": upload_id,
                    "error": msg,
                }
                notifier.publish_scan_results_sync(ui_event)
            except Exception:
                pass
            return self._result_payload(status="ERROR", upload_id=upload_id, response=resp_json, message=msg)
        except Exception as e:
            # Any other DIANNA-side error: log and continue; no retry, no DLQ
            msg = str(e)
            dsx_logging.warning(f"[dianna:{self.context.task_id}] DIANNA unexpected error: {e}")
            try:
                from dsx_connect.messaging.bus import SyncBus
                from dsx_connect.messaging.notifiers import Notifiers
                from dsx_connect.config import get_config as _gc
                bus = SyncBus(str(_gc().redis_url))
                notifier = Notifiers(bus)
                ui_event = {
                    "type": "dianna_analysis",
                    "status": "ERROR",
                    "location": scan_req.location,
                    "connector_url": scan_req.connector_url,
                    "sha256": sha256,
                    "upload_id": upload_id,
                    "error": msg,
                }
                notifier.publish_scan_results_sync(ui_event)
            except Exception:
                pass
            return self._result_payload(status="ERROR", upload_id=upload_id, response=resp_json, message=msg)

        # Best-effort syslog emission of analysis event (upload + optional result)
        try:
            base_evt = {
                "event": "dianna_analysis",
                "location": scan_req.location,
                "connector_url": scan_req.connector_url,
                "sha256": sha256,
                "upload_id": upload_id,
            }
            from json import dumps
            # Upload completion
            syslog_logger.info(dumps({**base_evt, "phase": "QUEUED", "response": resp_json or {}}))
            # Final result if available
            if analysis_result:
                try:
                    syslog_logger.info(dumps({**base_evt, "phase": "RESULT", "analysis": analysis_result}))
                except Exception:
                    pass
        except Exception:
            pass

        dsx_logging.info(
            f"[dianna:{self.context.task_id}] analysis queued for {scan_req.location} (sha256={sha256[:12]}...)"
        )
        analysis_id = None
        if isinstance(resp_json, dict):
            analysis_id = resp_json.get("analysisId") or resp_json.get("analysis_id")
        message = None
        if not upload_id and not analysis_id:
            message = "no analysis identifier returned by DIANNA; likely no accepted upload"
        return self._result_payload(
            status="QUEUED",
            analysis_id=analysis_id,
            upload_id=upload_id,
            response=resp_json,
            message=message,
        )

    def _read_file_stream_from_connector(self, scan_request: ScanRequestModel, chunk_size: int):
        try:
            with get_connector_client(scan_request.connector_url) as client:
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
                    for chunk in response.iter_bytes(chunk_size=chunk_size):
                        if chunk:
                            yield chunk
                finally:
                    response.close()

            return iter_chunks(), size
        except httpx.ConnectError as e:
            raise ConnectorConnectionError(f"Connector connection failed: {e}") from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if 500 <= code < 600:
                raise ConnectorServerError(f"Connector server error {code}") from e
            elif 400 <= code < 500:
                raise ConnectorClientError(f"Connector client error {code}") from e
            raise ConnectorConnectionError(f"Connector HTTP error {code}") from e

    def _read_file_from_connector(self, scan_request: ScanRequestModel) -> bytes:
        try:
            with get_connector_client(scan_request.connector_url) as client:
                response = client.post(
                    ConnectorAPI.READ_FILE,
                    json_body=jsonable_encoder(scan_request),
                )
            response.raise_for_status()
            return response.content
        except httpx.ConnectError as e:
            raise ConnectorConnectionError(f"Connector connection failed: {e}") from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if 500 <= code < 600:
                raise ConnectorServerError(f"Connector server error {code}") from e
            elif 400 <= code < 500:
                raise ConnectorClientError(f"Connector client error {code}") from e
            raise ConnectorConnectionError(f"Connector HTTP error {code}") from e

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
        # Minimal DLQ: reuse scan_request item shape for troubleshooting
        try:
            from dsx_connect.taskworkers.dlq_store import enqueue_scan_request_dlq_sync, make_scan_request_dlq_item
            scan_request_dict = args[0] if len(args) > 0 else {}
            item = make_scan_request_dlq_item(
                scan_request=scan_request_dict,
                error=error,
                reason=f"dianna:{reason}",
                scan_request_task_id=scan_request_task_id or current_task_id,
                current_task_id=current_task_id,
                retry_count=retry_count,
                upstream_task_id=upstream_task_id,
            )
            enqueue_scan_request_dlq_sync(item)
        except Exception:
            pass


# Register the task
celery_app.register_task(DiannaAnalysisWorker())
