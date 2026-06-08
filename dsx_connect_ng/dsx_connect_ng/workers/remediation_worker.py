from __future__ import annotations

import argparse
import asyncio
import json
from typing import Awaitable, Callable

from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.service import ControlPlaneService
from dsx_connect_ng.jobs.contracts import MessageEnvelope, RemediationRequested
from dsx_connect_ng.jobs.models import RemediationResult, RemediationStageUpdateRequest
from dsx_connect_ng.readers.base import TerminalScanError
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.connector_actions import execute_connector_item_action
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


RemediationExecutor = Callable[[RemediationRequested], Awaitable[RemediationResult]]


async def process_remediation_message(
    service: JobService,
    envelope: MessageEnvelope,
    *,
    execute_remediation: RemediationExecutor,
) -> None:
    request = RemediationRequested.from_envelope(envelope)
    service.update_remediation_stage(
        request.job_item_id,
        RemediationStageUpdateRequest(state="running").as_stage_update_request(),
        refresh_parent=False,
    )
    result = await execute_remediation(request)
    await service.advance_remediation_stage(
        request.job_item_id,
        RemediationStageUpdateRequest(state="completed", remediation_result=result).as_stage_update_request(),
    )


async def stub_remediation_executor(request: RemediationRequested) -> RemediationResult:
    plan = request.remediation_plan.remediation_plan
    connector_action = request.as_connector_action_request()
    action = str(plan.get("action") or "noop")
    target_path = plan.get("targetPath") or plan.get("target_path")
    if target_path is None and action == "quarantine":
        target_path = f"/quarantine/{request.job_item_id}"
    details = {
        "worker": "remediation_stub",
        "tagApplied": bool(plan.get("tag")) if action in {"quarantine", "tag_only"} else False,
        "connectorAction": connector_action.model_dump(mode="json"),
    }
    if plan.get("quarantineTarget") is not None:
        details["quarantineTarget"] = plan.get("quarantineTarget")
    return RemediationResult(
        action=action,
        outcome="succeeded",
        targetPath=target_path,
        details=details,
    )


def build_remediation_executor(service: JobService) -> RemediationExecutor:
    control_plane: ControlPlaneService | None = service.control_plane

    async def execute(request: RemediationRequested) -> RemediationResult:
        connector_action = request.as_connector_action_request()
        if connector_action.item_action == "nothing":
            return await stub_remediation_executor(request)
        if request.integration_id is None or control_plane is None:
            return await stub_remediation_executor(request)
        try:
            return await execute_connector_item_action(request, control_plane=control_plane)
        except TerminalScanError:
            raise
        except Exception:
            # Best-effort phase: keep local stub path available when connector action transport/config is absent.
            return await stub_remediation_executor(request)

    return execute


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume remediation work queue and post remediation-stage callbacks.")
    parser.add_argument("--queue", default="dsx.ng.remediation", help="RabbitMQ work queue to consume.")
    parser.add_argument("--routing-key", default="remediation.requested", help="Routing key to bind.")
    parser.add_argument("--prefetch-count", type=int, default=1, help="Consumer prefetch count.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    executor = build_remediation_executor(service)
    print(json.dumps({"event": "remediation_worker_start", **summary, "queue": args.queue}), flush=True)

    async def handle(envelope: MessageEnvelope) -> None:
        await process_remediation_message(service, envelope, execute_remediation=executor)

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
