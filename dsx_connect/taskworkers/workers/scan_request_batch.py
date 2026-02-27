from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

from shared.models.connector_models import ScanRequestModel
from shared.dsx_logging import dsx_logging
from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.dlq_store import enqueue_scan_request_dlq_sync, make_scan_request_dlq_item
from dsx_connect.taskworkers.errors import MalformedScanRequest
from dsx_connect.taskworkers.names import Queues, Tasks
from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryGroups


class ScanRequestBatchWorker(BaseWorker):
    """
    Batch dispatcher for scan requests.
    This task validates a list of scan requests and fans them out to the existing
    single-item scan request queue in chunks.
    """

    name = Tasks.REQUEST_BATCH
    RETRY_GROUPS = RetryGroups.none()

    def execute(
        self,
        scan_requests: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
        scan_request_task_id: str | None = None,
    ) -> str:
        if not isinstance(scan_requests, list) or not scan_requests:
            raise MalformedScanRequest("scan_requests must be a non-empty list")

        validated: list[dict[str, Any]] = []
        for idx, item in enumerate(scan_requests):
            try:
                req = ScanRequestModel.model_validate(item)
            except ValidationError as e:
                raise MalformedScanRequest(f"Invalid scan request at index {idx}: {e}") from e
            validated.append(req.model_dump())

        configured_batch_size = self._resolve_batch_size(batch_size)
        total = len(validated)
        enqueued = 0
        root_id = scan_request_task_id or getattr(self.request, "id", None)

        for start in range(0, total, configured_batch_size):
            chunk = validated[start:start + configured_batch_size]
            for req in chunk:
                celery_app.send_task(
                    Tasks.REQUEST,
                    args=[req],
                    kwargs={"scan_request_task_id": root_id},
                    queue=Queues.REQUEST,
                )
                enqueued += 1

            dsx_logging.info(
                f"[scan_request_batch:{getattr(self.context, 'task_id', 'unknown')}] "
                f"enqueued chunk {start // configured_batch_size + 1} "
                f"({len(chunk)} items, total_enqueued={enqueued}/{total})"
            )

        return f"ENQUEUED:{enqueued}"

    @staticmethod
    def _resolve_batch_size(batch_size: int | None) -> int:
        if isinstance(batch_size, int) and batch_size > 0:
            return batch_size
        try:
            env_val = int(os.getenv("DSXCONNECT_SCAN_REQUEST_BATCH_SIZE", "10"))
            if env_val > 0:
                return env_val
        except Exception:
            pass
        return 10

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
        batch = args[0] if len(args) > 0 and isinstance(args[0], list) else []
        summary = {
            "batch_count": len(batch),
            "first_item": batch[0] if batch else {},
        }
        item = make_scan_request_dlq_item(
            scan_request=summary,
            error=error,
            reason=reason,
            scan_request_task_id=scan_request_task_id,
            current_task_id=current_task_id,
            retry_count=retry_count,
            upstream_task_id=upstream_task_id,
        )
        enqueue_scan_request_dlq_sync(item)


celery_app.register_task(ScanRequestBatchWorker())
