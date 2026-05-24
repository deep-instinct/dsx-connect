from __future__ import annotations

import argparse
import asyncio
import json

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.models import OutboxFlushResult
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.runtime import build_job_service


async def relay_once(service: JobService, *, limit: int) -> OutboxFlushResult:
    return await service.flush_outbox(limit=limit)


async def relay_forever(
    service: JobService,
    *,
    limit: int,
    poll_interval_seconds: float,
) -> None:
    while True:
        result = await relay_once(service, limit=limit)
        print(
            json.dumps(
                {
                    "event": "relay_flush",
                    "attempted": result.attempted,
                    "published": result.published,
                    "failed": result.failed,
                }
            ),
            flush=True,
        )
        await asyncio.sleep(poll_interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retry pending execution outbox records.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Flush pending outbox records once and exit.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.relay.batch_size,
        help="Maximum pending outbox records to process per flush.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=settings.relay.poll_interval_seconds,
        help="Sleep interval between flush cycles in continuous mode.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    service, summary = build_job_service()
    print(json.dumps({"event": "relay_start", **summary}), flush=True)
    if args.once:
        result = await relay_once(service, limit=args.batch_size)
        print(
            json.dumps(
                {
                    "event": "relay_flush",
                    "attempted": result.attempted,
                    "published": result.published,
                    "failed": result.failed,
                }
            ),
            flush=True,
        )
        return
    await relay_forever(
        service,
        limit=args.batch_size,
        poll_interval_seconds=args.poll_interval_seconds,
    )


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
