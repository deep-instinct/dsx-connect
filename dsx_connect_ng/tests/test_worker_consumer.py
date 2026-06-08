import asyncio
import json
from types import SimpleNamespace

from dsx_connect_ng.jobs.contracts import MessageEnvelope
from dsx_connect_ng.workers.consumer import (
    connect_robust_with_retry,
    decode_envelope,
    dispatch_body,
    dlq_queue_name,
    next_retry_attempt,
    retry_queue_name,
    should_retry,
)


def test_decode_envelope_parses_message_body() -> None:
    body = json.dumps(
        {
            "message_type": "scan_item_requested",
            "job_id": "job-1",
            "job_item_id": "item-1",
            "object_identity": "/finance/a.pdf",
            "payload": {"scan_options": {"protectedEntity": 1}},
        }
    ).encode("utf-8")

    envelope = decode_envelope(body)

    assert isinstance(envelope, MessageEnvelope)
    assert envelope.message_type == "scan_item_requested"
    assert envelope.payload["scan_options"]["protectedEntity"] == 1


def test_dispatch_body_invokes_handler_with_envelope() -> None:
    seen: list[MessageEnvelope] = []

    async def handler(envelope: MessageEnvelope) -> None:
        seen.append(envelope)

    body = json.dumps(
        {
            "message_type": "policy_evaluation_requested",
            "job_id": "job-2",
            "job_item_id": "item-2",
            "object_identity": "/finance/bad.exe",
            "payload": {"scan_result": {"verdict": "Malicious"}},
        }
    ).encode("utf-8")

    asyncio.run(dispatch_body(handler, body))

    assert len(seen) == 1
    assert seen[0].message_type == "policy_evaluation_requested"


def test_retry_queue_name_and_dlq_queue_name() -> None:
    assert retry_queue_name("dsx.ng.scan") == "dsx.ng.scan.retry"
    assert dlq_queue_name("dsx.ng.scan") == "dsx.ng.scan.dlq"


def test_next_retry_attempt_defaults_to_one() -> None:
    assert next_retry_attempt(None) == 1
    assert next_retry_attempt({}) == 1


def test_next_retry_attempt_increments_existing_header() -> None:
    assert next_retry_attempt({"x-dsx-retry-attempt": 1}) == 2
    assert next_retry_attempt({"x-dsx-retry-attempt": "2"}) == 3


def test_should_retry_respects_max_attempts() -> None:
    assert should_retry(headers=None, max_attempts=3) is True
    assert should_retry(headers={"x-dsx-retry-attempt": 2}, max_attempts=3) is True
    assert should_retry(headers={"x-dsx-retry-attempt": 3}, max_attempts=3) is False


def test_connect_robust_with_retry_retries_initial_broker_failure() -> None:
    state = SimpleNamespace(attempts=0)
    connection = object()

    class FakeAioPika:
        @staticmethod
        async def connect_robust(_url: str):
            state.attempts += 1
            if state.attempts == 1:
                raise RuntimeError("broker starting")
            return connection

    result = asyncio.run(
        connect_robust_with_retry(
            FakeAioPika,
            "amqp://localhost",
            retry_interval_seconds=0,
        )
    )

    assert result is connection
    assert state.attempts == 2


def test_successful_dispatch_should_ack_message() -> None:
    state = SimpleNamespace(acked=False)

    class FakeMessage:
        def __init__(self, body: bytes) -> None:
            self.body = body

        async def ack(self) -> None:
            state.acked = True

    async def handler(_envelope: MessageEnvelope) -> None:
        return None

    body = json.dumps(
        {
            "message_type": "scan_item_requested",
            "job_id": "job-1",
            "job_item_id": "item-1",
            "object_identity": "/finance/a.pdf",
            "payload": {},
        }
    ).encode("utf-8")

    async def simulate() -> None:
        message = FakeMessage(body)
        await dispatch_body(handler, message.body)
        await message.ack()

    asyncio.run(simulate())

    assert state.acked is True
