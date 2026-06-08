from __future__ import annotations

import argparse
import asyncio
import json
from typing import Awaitable, Callable

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import MessageEnvelope, ResultSinkEmitRequested
from dsx_connect_ng.jobs.models import DeliveryResult, DeliveryStageUpdateRequest
from dsx_connect_ng.result_sink.base import ResultSink
from dsx_connect_ng.result_sink.bootstrap import build_result_sink
from dsx_connect_ng.result_sink.models import ResultSinkEvent
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


ResultSinkExecutor = Callable[[ResultSinkEmitRequested], Awaitable[DeliveryResult]]


async def process_result_sink_message(
    service: JobService,
    envelope: MessageEnvelope,
    *,
    execute_result_sink: ResultSinkExecutor,
) -> None:
    request = ResultSinkEmitRequested.from_envelope(envelope)
    if request.result_type != "workflow_summary":
        await execute_result_sink(request)
        return
    service.update_delivery_stage(
        request.job_item_id,
        DeliveryStageUpdateRequest(state="running").as_stage_update_request(),
        refresh_parent=False,
    )
    result = await execute_result_sink(request)
    await service.advance_delivery_stage(
        request.job_item_id,
        DeliveryStageUpdateRequest(state="completed", delivery_result=result).as_stage_update_request(),
    )


async def stub_result_sink_executor(request: ResultSinkEmitRequested) -> DeliveryResult:
    target = request.delivery_target.delivery_target
    destination = target.get("connector") or target.get("destination") or "unknown"
    return DeliveryResult(
        destination=destination,
        outcome="delivered",
        externalReference=f"delivery-{request.job_item_id}",
        details={"worker": "result_sink_stub", "result_type": request.result_type},
    )


def build_result_sink_executor(sink: ResultSink) -> ResultSinkExecutor:
    async def execute(request: ResultSinkEmitRequested) -> DeliveryResult:
        event = ResultSinkEvent.from_result_sink_emit_request(request)
        await sink.emit(event)
        target = request.delivery_target.delivery_target
        destination = target.get("connector") or target.get("destination") or "result_sink"
        return DeliveryResult(
            destination=destination,
            outcome="emitted",
            externalReference=f"result-sink-{request.job_item_id}",
            details={"worker": "result_sink_adapter", "result_type": request.result_type},
        )

    return execute


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume result-sink work queue and emit ResultSink events.")
    parser.add_argument("--queue", default="dsx.ng.result_sink", help="RabbitMQ work queue to consume.")
    parser.add_argument("--routing-key", default="result_sink.emit.requested", help="Primary routing key to bind.")
    parser.add_argument("--prefetch-count", type=int, default=1, help="Consumer prefetch count.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    sink = build_result_sink()
    print(json.dumps({"event": "result_sink_worker_start", **summary, "queue": args.queue}), flush=True)

    async def handle(envelope: MessageEnvelope) -> None:
        await process_result_sink_message(service, envelope, execute_result_sink=build_result_sink_executor(sink))

    routing_keys = [args.routing_key]
    if "delivery.requested" not in routing_keys:
        routing_keys.append("delivery.requested")
    if "result_sink.emit.requested" not in routing_keys:
        routing_keys.append("result_sink.emit.requested")

    await consume_queue(
        amqp_url=settings.rabbitmq.url,
        exchange_name=settings.rabbitmq.job_exchange,
        queue_name=args.queue,
        routing_keys=routing_keys,
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


# Legacy aliases kept during the worker rename.
DeliveryExecutor = ResultSinkExecutor
process_delivery_message = process_result_sink_message
stub_delivery_executor = stub_result_sink_executor
