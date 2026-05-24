from __future__ import annotations

import argparse
import asyncio
import json
from typing import Awaitable, Callable

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import DiannaAnalysisRequested, MessageEnvelope
from dsx_connect_ng.jobs.models import DiannaResult, DiannaStageUpdateRequest
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


DiannaExecutor = Callable[[DiannaAnalysisRequested], Awaitable[DiannaResult]]


async def process_dianna_message(
    service: JobService,
    envelope: MessageEnvelope,
    *,
    execute_dianna: DiannaExecutor,
) -> None:
    request = DiannaAnalysisRequested.from_envelope(envelope)
    await service.advance_dianna_stage(
        request.job_item_id,
        DiannaStageUpdateRequest(state="running").as_stage_update_request(),
    )
    result = await execute_dianna(request)
    await service.advance_dianna_stage(
        request.job_item_id,
        DiannaStageUpdateRequest(state="completed", dianna_result=result).as_stage_update_request(),
    )


async def stub_dianna_executor(request: DiannaAnalysisRequested) -> DiannaResult:
    return DiannaResult(
        analysisId=f"dianna-{request.job_item_id}",
        status="completed",
        details={
            "worker": "dianna_stub",
            "reason": request.request_reason,
            "contentSourceMode": request.content_source.mode,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume DIANNA work queue and post dianna-stage callbacks.")
    parser.add_argument("--queue", default="dsx.ng.dianna", help="RabbitMQ work queue to consume.")
    parser.add_argument("--routing-key", default="dianna.requested", help="Routing key to bind.")
    parser.add_argument("--prefetch-count", type=int, default=1, help="Consumer prefetch count.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    print(json.dumps({"event": "dianna_worker_start", **summary, "queue": args.queue}), flush=True)

    async def handle(envelope: MessageEnvelope) -> None:
        await process_dianna_message(service, envelope, execute_dianna=stub_dianna_executor)

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
