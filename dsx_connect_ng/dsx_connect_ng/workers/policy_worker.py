from __future__ import annotations

import argparse
import asyncio
import json
from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import MessageEnvelope, PolicyEvaluationRequested
from dsx_connect_ng.jobs.models import PolicyStageUpdateRequest
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.policy_engine import LegacyPolicyEvaluator, stub_policy_evaluator
from dsx_connect_ng.workers.runtime import build_job_service


async def process_policy_message(
    service: JobService,
    envelope: MessageEnvelope,
    *,
    evaluate_policy: LegacyPolicyEvaluator,
) -> None:
    request = PolicyEvaluationRequested.from_envelope(envelope)
    await service.advance_policy_stage(
        request.job_item_id,
        PolicyStageUpdateRequest(state="running").as_stage_update_request(),
    )
    decision = await evaluate_policy(request)
    await service.advance_policy_stage(
        request.job_item_id,
        PolicyStageUpdateRequest(state="completed", decision=decision).as_stage_update_request(),
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consume policy work queue and post policy-stage callbacks.")
    parser.add_argument("--queue", default="dsx.ng.policy", help="RabbitMQ work queue to consume.")
    parser.add_argument("--routing-key", default="policy.requested", help="Routing key to bind.")
    parser.add_argument("--prefetch-count", type=int, default=1, help="Consumer prefetch count.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    print(json.dumps({"event": "policy_worker_start", **summary, "queue": args.queue}), flush=True)

    async def handle(envelope: MessageEnvelope) -> None:
        await process_policy_message(service, envelope, evaluate_policy=stub_policy_evaluator)

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
