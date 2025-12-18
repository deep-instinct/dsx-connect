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

    def execute(self, scan_request_dict: dict, *, archive_password: str | None = None,
                scan_request_task_id: str | None = None) -> str:
        # Validate minimal scan request using existing model
        scan_req = ScanRequestModel.model_validate(scan_request_dict)

        # Fetch file bytes from connector
        file_bytes = self._read_file_from_connector(scan_req)
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Upload to DIANNA
        cfg = get_config().dianna
        url = cfg.management_url.rstrip('/') + '/api/v1/dianna/analyzeFile'
        headers = {"Authorization": f"{cfg.api_token}"} if cfg.api_token else {}
        timeout = httpx.Timeout(cfg.timeout)

        resp_json: Optional[Dict[str, Any]] = None
        upload_id: Optional[str] = None

        analysis_result: Optional[Dict[str, Any]] = None
        try:
            with httpx.Client(timeout=timeout, verify=(cfg.ca_bundle or cfg.verify_tls)) as client:
                total_size = len(file_bytes)
                chunk_size = int(cfg.chunk_size)
                total_chunks = (total_size + chunk_size - 1) // chunk_size
                for idx in range(total_chunks):
                    start = idx * chunk_size
                    chunk = file_bytes[start:start + chunk_size]
                    payload = {
                        'start_byte': start,
                        'end_byte': start + len(chunk) - 1,
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

                # Initial notify: upload completed, analysis queued
                try:
                    from dsx_connect.messaging.bus import SyncBus
                    from dsx_connect.messaging.notifiers import Notifiers
                    from dsx_connect.config import get_config as _gc
                    bus = SyncBus(str(_gc().redis_url))
                    notifier = Notifiers(bus)
                    ui_event = {
                        "type": "dianna_analysis",
                        "status": "QUEUED",
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
                                if status in {"SUCCESS", "FAILED", "ERROR", "CANCELLED"}:
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
            return "ERROR"
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
            return "ERROR"
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
            return "ERROR"

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

        # Publish a lightweight SSE event for the UI (reuse scan-result channel)
        try:
            from dsx_connect.messaging.bus import SyncBus
            from dsx_connect.messaging.notifiers import Notifiers
            from dsx_connect.config import get_config as _gc
            bus = SyncBus(str(_gc().redis_url))
            notifier = Notifiers(bus)
            ui_event = {
                "type": "dianna_analysis",
                "location": scan_req.location,
                "connector_url": scan_req.connector_url,
                "sha256": sha256,
                "upload_id": upload_id,
            }
            notifier.publish_scan_results_sync(ui_event)
        except Exception:
            pass

        dsx_logging.info(
            f"[dianna:{self.context.task_id}] analysis queued for {scan_req.location} (sha256={sha256[:12]}...)"
        )
        return upload_id or "OK"

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
