# … existing imports …
import io
import unicodedata

import httpx
from celery import states
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryDecision, RetryGroups
from dsx_connect.config import get_config
from dsx_connect.taskworkers.dlq_store import enqueue_scan_request_dlq_sync, make_scan_request_dlq_item

from dsx_connect.connectors.client import get_connector_client
from dsx_connect.dsxa_client.dsxa_client import DSXAClientError, DSXAServiceError, DSXATimeoutError, \
    DSXAConnectionError, DSXAScanRequest, DSXAClient
from shared.models.connector_models import ScanRequestModel
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.errors import MalformedScanRequest, DsxaClientError, DsxaServerError, DsxaTimeoutError, \
    ConnectorClientError, ConnectorServerError, ConnectorConnectionError
from dsx_connect.taskworkers.names import Tasks, Queues
import redis  # lightweight sync client for quick job-state checks
from shared.dsx_logging import dsx_logging
from shared.routes import ConnectorAPI

class ScanRequestWorker(BaseWorker):
    """
    Celery task to process incoming scan requests.
    Validates the request, fetches the file, scans it via DSXA, and dispatches a
    verdict task. Error handling, retries, and DLQ submission are delegated to
    BaseWorker.
    """
    name = Tasks.REQUEST
    RETRY_GROUPS = RetryGroups.connector_and_dsxa()

    def execute(self, scan_request_dict: dict, *, scan_request_task_id: str = None) -> str:
        # 1. Validate input (convert Pydantic errors to our domain error)
        try:
            scan_request = ScanRequestModel.model_validate(scan_request_dict)
        except ValidationError as e:
            raise MalformedScanRequest(f"Invalid scan request: {e}") from e

        # 1a. Respect job pause/cancel (best-effort): quick sync Redis check
        job_id = getattr(scan_request, "scan_job_id", None)
        if job_id:
            try:
                cfg = get_config()
                r = redis.Redis.from_url(str(cfg.redis_url), decode_responses=True)
                key = f"dsxconnect:job:{job_id}"
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

        # 2. Read file from connector
        file_bytes = self.read_file_from_connector(scan_request)
        dsx_logging.debug(f"[scan_request:{self.context.task_id}] Read {len(file_bytes)} bytes")

        # 3. Scan with DSXA
        dpa_verdict = self.scan_with_dsxa(file_bytes, scan_request, self.context.task_id)
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


    def read_file_from_connector(self, scan_request: ScanRequestModel) -> bytes:
        """Read file bytes from connector. Maps exceptions to task-appropriate errors."""
        target = scan_request.connector or scan_request.connector_url
        try:
            with get_connector_client(target) as client:
                response = client.post(
                    ConnectorAPI.READ_FILE,
                    json_body=jsonable_encoder(scan_request),
                )
            response.raise_for_status()
            return response.content

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


    def scan_with_dsxa(self, file_bytes: bytes, scan_request: ScanRequestModel, task_id: str = None):
        """Scan file with DSXA. Maps exceptions to task-appropriate errors."""
        config = get_config()
        dsxa_client = DSXAClient(scan_binary_url=config.scanner.scan_binary_url)

        # Prepare metadata
        safe_meta = unicodedata.normalize("NFKD", scan_request.metainfo).encode("ascii", "ignore").decode("ascii")
        metadata_info = f"file-tag:{safe_meta}"
        if task_id:
            metadata_info += f",task-id:{task_id}"

        try:
            dpa_verdict = dsxa_client.scan_binary(
                scan_request=DSXAScanRequest(
                    binary_data=io.BytesIO(file_bytes),
                    metadata_info=metadata_info
                )
            )

            # Handle special "initializing" case
            reason = getattr(dpa_verdict.verdict_details, "reason", "") or ""
            if dpa_verdict.verdict.value == "Not Scanned" and "initializing" in reason:
                raise DsxaServerError("DSXA scanner is initializing")

            return dpa_verdict

        except DSXAConnectionError as e:
            raise DsxaTimeoutError(f"DSXA connection failed: {e}") from e
        except DSXATimeoutError as e:
            raise DsxaTimeoutError(f"DSXA timeout: {e}") from e
        except DSXAServiceError as e:
            if any(code in str(e) for code in ["HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504"]):
                raise DsxaServerError(f"DSXA server error: {e}") from e
            raise DsxaClientError(f"DSXA client error: {e}") from e
        except DSXAClientError as e:
            raise DsxaClientError(f"DSXA client error: {e}") from e

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

# Register the class-based task with Celery
celery_app.register_task(ScanRequestWorker())
