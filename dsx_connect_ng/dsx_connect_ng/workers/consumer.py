from __future__ import annotations

import json
import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Any

from dsx_connect_ng.jobs.contracts import MessageEnvelope
from dsx_connect_ng.ops_logging import log_event, ops_logging
from dsx_connect_ng.workers.errors import TerminalWorkerError


EnvelopeHandler = Callable[[MessageEnvelope], Awaitable[None]]
TerminalFailureHandler = Callable[[MessageEnvelope, Exception, dict[str, Any]], Awaitable[None]]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


_WORKER_ACK_LOGGING = _env_bool("DSX_CONNECT_NG_LOCAL__WORKER_ACK_LOGGING", True)


def decode_envelope(body: bytes) -> MessageEnvelope:
    payload = json.loads(body.decode("utf-8"))
    return MessageEnvelope.model_validate(payload)


async def dispatch_body(handler: EnvelopeHandler, body: bytes) -> None:
    await handler(decode_envelope(body))


def retry_queue_name(queue_name: str) -> str:
    return f"{queue_name}.retry"


def dlq_queue_name(queue_name: str) -> str:
    return f"{queue_name}.dlq"


def next_retry_attempt(headers: dict[str, Any] | None) -> int:
    if not headers:
        return 1
    current = headers.get("x-dsx-retry-attempt")
    try:
        value = int(current)
    except (TypeError, ValueError):
        value = 0
    return value + 1


def should_retry(*, headers: dict[str, Any] | None, max_attempts: int) -> bool:
    return next_retry_attempt(headers) <= max_attempts


async def connect_robust_with_retry(
    aio_pika_module: Any,
    amqp_url: str,
    *,
    retry_interval_seconds: float = 2.0,
    max_attempts: int | None = None,
):
    attempt = 0
    while True:
        attempt += 1
        try:
            return await aio_pika_module.connect_robust(amqp_url)
        except Exception as exc:
            if max_attempts is not None and attempt >= max_attempts:
                raise
            print(
                json.dumps(
                    {
                        "event": "worker_broker_connect_retry",
                        "attempt": attempt,
                        "retry_interval_seconds": retry_interval_seconds,
                        "error": str(exc),
                    }
                ),
                flush=True,
            )
            await asyncio.sleep(retry_interval_seconds)


async def consume_queue(
    *,
    amqp_url: str,
    exchange_name: str,
    queue_name: str,
    routing_keys: list[str],
    handler: EnvelopeHandler,
    prefetch_count: int = 1,
    retry_exchange_name: str | None = None,
    dead_letter_exchange_name: str | None = None,
    retry_delay_ms: int = 5000,
    retry_max_attempts: int = 5,
    broker_connect_retry_interval_seconds: float = 2.0,
    broker_connect_max_attempts: int | None = None,
    terminal_failure_handler: TerminalFailureHandler | None = None,
) -> None:
    try:
        import aio_pika
    except ImportError as exc:
        raise RuntimeError("aio_pika_not_installed") from exc

    connection = await connect_robust_with_retry(
        aio_pika,
        amqp_url,
        retry_interval_seconds=broker_connect_retry_interval_seconds,
        max_attempts=broker_connect_max_attempts,
    )
    try:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=prefetch_count)
        exchange = await channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        retry_exchange = None
        dlx_exchange = None
        if retry_exchange_name:
            retry_exchange = await channel.declare_exchange(
                retry_exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
        if dead_letter_exchange_name:
            dlx_exchange = await channel.declare_exchange(
                dead_letter_exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
        queue = await channel.declare_queue(queue_name, durable=True)
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)
        if retry_exchange is not None:
            retry_queue = await channel.declare_queue(
                retry_queue_name(queue_name),
                durable=True,
                arguments={
                    "x-message-ttl": retry_delay_ms,
                    "x-dead-letter-exchange": exchange_name,
                    "x-dead-letter-routing-key": routing_keys[0],
                },
            )
            await retry_queue.bind(retry_exchange, routing_keys[0])
        if dlx_exchange is not None:
            dlq = await channel.declare_queue(dlq_queue_name(queue_name), durable=True)
            await dlq.bind(dlx_exchange, routing_keys[0])

        semaphore = asyncio.Semaphore(prefetch_count)
        in_flight: set[asyncio.Task[None]] = set()

        async def handle_message(message) -> None:
            async with semaphore:
                envelope: MessageEnvelope | None = None
                try:
                    envelope = decode_envelope(message.body)
                    await handler(envelope)
                    await message.ack()
                    if _WORKER_ACK_LOGGING:
                        log_event(
                            ops_logging,
                            20,
                            "worker_message_acked",
                            queue=queue_name,
                            message_type=envelope.message_type,
                            job_id=envelope.job_id,
                            job_item_id=envelope.job_item_id,
                            object_identity=envelope.object_identity,
                        )
                except TerminalWorkerError:
                    if dlx_exchange is not None:
                        headers = dict(message.headers or {})
                        headers["x-dsx-terminal"] = True
                        dlq_message = aio_pika.Message(
                            body=message.body,
                            headers=headers,
                            content_type=message.content_type,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        )
                        await dlx_exchange.publish(dlq_message, routing_key=routing_keys[0])
                    await message.ack()
                except Exception as exc:
                    if retry_exchange is not None and should_retry(headers=message.headers, max_attempts=retry_max_attempts):
                        headers = dict(message.headers or {})
                        headers["x-dsx-retry-attempt"] = next_retry_attempt(message.headers)
                        retry_message = aio_pika.Message(
                            body=message.body,
                            headers=headers,
                            content_type=message.content_type,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        )
                        await retry_exchange.publish(retry_message, routing_key=routing_keys[0])
                        await message.ack()
                        return
                    if terminal_failure_handler is not None and envelope is not None:
                        headers = dict(message.headers or {})
                        headers["x-dsx-retry-attempt"] = next_retry_attempt(message.headers) - 1
                        await terminal_failure_handler(envelope, exc, headers)
                    if dlx_exchange is not None:
                        headers = dict(message.headers or {})
                        headers["x-dsx-retry-attempt"] = next_retry_attempt(message.headers) - 1
                        dlq_message = aio_pika.Message(
                            body=message.body,
                            headers=headers,
                            content_type=message.content_type,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        )
                        await dlx_exchange.publish(dlq_message, routing_key=routing_keys[0])
                        await message.ack()
                        return
                    await message.nack(requeue=True)

        async with queue.iterator() as iterator:
            async for message in iterator:
                task = asyncio.create_task(handle_message(message))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
                if len(in_flight) >= prefetch_count:
                    done, _pending = await asyncio.wait(in_flight, return_when=asyncio.FIRST_COMPLETED)
                    for completed in done:
                        completed.result()
    finally:
        if 'in_flight' in locals() and in_flight:
            await asyncio.gather(*in_flight)
        await connection.close()
