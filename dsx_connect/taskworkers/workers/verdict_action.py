# dsx_connect/taskworkers/workers/verdict_action.py
from __future__ import annotations
from typing import Any, Dict

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues
from dsx_connect.taskworkers.workers.base_worker import BaseWorker, RetryGroup, RetryGroups
from dsx_connect.taskworkers.dlq_store import enqueue_verdict_action_dlq_sync, make_verdict_action_dlq_item

from dsx_connect.connectors.client import get_connector_client
from dsx_connect.dsxa_client.verdict_models import DPAVerdictModel2, DPAVerdictEnum
from shared.models.connector_models import ScanRequestModel, ItemActionEnum
from shared.dsx_logging import dsx_logging
from shared.routes import ConnectorAPI
from shared.models.status_responses import StatusResponseEnum, ItemActionStatusResponse


class VerdictActionWorker(BaseWorker):
    name = Tasks.VERDICT
    RETRY_GROUPS = RetryGroups.connector()

    def execute(self, scan_request_dict: Dict[str, Any],
                verdict_dict: Dict[str, Any], scan_request_task_id: str) -> str:
        # 1) validate inputs
        try:
            scan_request = ScanRequestModel.model_validate(scan_request_dict)
            verdict = DPAVerdictModel2.model_validate(verdict_dict)
            dsx_logging.debug(f"Processing {scan_request} for scan verdict: {verdict}")
        except ValidationError as e:
            dsx_logging.error(f"Failed to validate scan request or verdict: {e}", exc_info=True)
            return StatusResponseEnum.ERROR

        # 2) derive action from policy + verdict
        item_action_response = ItemActionStatusResponse(
            status=StatusResponseEnum.NOTHING,
            item_action=ItemActionEnum.NOTHING,
            message="No action taken",
        )

        if verdict.verdict == DPAVerdictEnum.MALICIOUS:
            # 2a. Call item_action if verdict is MALICIOUS and perhaps in some future - where the severity meets a threshold
            dsx_logging.info(f"Verdict is MALICIOUS, calling item_action")
            target = scan_request.connector or scan_request.connector_url
            with get_connector_client(target) as client:
                response = client.put(
                    ConnectorAPI.ITEM_ACTION,
                    json_body=jsonable_encoder(scan_request),
                )

            try:
                item_action_response = ItemActionStatusResponse.model_validate(response.json())
            except ValidationError as e:
                dsx_logging.error(f"ItemActionStatusResponse validation failed: {e}", exc_info=True)
                # Fallback to an “error” response
                item_action_response = ItemActionStatusResponse(
                    status=StatusResponseEnum.ERROR,
                    item_action=ItemActionEnum.NOT_IMPLEMENTED,
                    message="Invalid response from item_action endpoint",
                    description=str(e),
                )
            dsx_logging.info(f"Item action triggered successfully for {scan_request.location}")

        # 3) dispatch result task
        next_id = celery_app.send_task(
            Tasks.RESULT,
            args=[scan_request_dict, verdict.model_dump(), item_action_response.model_dump()],
            kwargs={"scan_request_task_id": scan_request_task_id},  # forward root id
            queue=Queues.RESULT,
        )

        dsx_logging.info(f"[verdict_action:{self.context.task_id}] -> scan_result {next_id}")
        return "SUCCESS"

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
        # args: [scan_request_dict, verdict_dict, scan_request_task_id (if you passed it positionally, ignore)]
        scan_request_dict = args[0] if len(args) > 0 else {}
        verdict_dict      = args[1] if len(args) > 1 else {}

        item = make_verdict_action_dlq_item(
            scan_request=scan_request_dict,
            verdict=verdict_dict,
            error=error,
            reason=reason,
            scan_request_task_id=scan_request_task_id,  # forwarded root id
            current_task_id=current_task_id,            # this failing task
            retry_count=retry_count,
            upstream_task_id=upstream_task_id,
        )
        enqueue_verdict_action_dlq_sync(item)
# Register with Celery
celery_app.register_task(VerdictActionWorker())
