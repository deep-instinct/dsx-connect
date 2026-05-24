from __future__ import annotations

import json

from dsx_connect_ng.config import AppSettings
from dsx_connect_ng.jobs.bus import JobBus, PublishableMessage
from dsx_connect_ng.jobs.contracts import MessageEnvelope
from dsx_connect_ng.jobs.models import DomainJobEnvelope


class RabbitMQJobBus(JobBus):
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    async def publish(self, job: PublishableMessage) -> None:
        try:
            import aio_pika
        except ImportError as exc:
            raise RuntimeError("aio_pika_not_installed") from exc

        connection = await aio_pika.connect_robust(self.settings.rabbitmq.url)
        try:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                self.settings.rabbitmq.job_exchange,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            message = aio_pika.Message(
                body=json.dumps(job.model_dump(mode="json")).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            if isinstance(job, MessageEnvelope):
                routing_key = {
                    "scan_item_requested": "scan.requested",
                    "scan_item_completed": "scan.completed",
                    "scan_item_failed": "scan.failed",
                    "policy_evaluation_requested": "policy.requested",
                    "policy_evaluation_completed": "policy.completed",
                    "policy_evaluation_failed": "policy.failed",
                    "dianna_analysis_requested": "dianna.requested",
                    "dianna_analysis_completed": "dianna.completed",
                    "dianna_analysis_failed": "dianna.failed",
                    "remediation_requested": "remediation.requested",
                    "remediation_completed": "remediation.completed",
                    "remediation_failed": "remediation.failed",
                    "result_sink_emit_requested": "result_sink.emit.requested",
                    "result_sink_emit_completed": "result_sink.emit.completed",
                    "result_sink_emit_failed": "result_sink.emit.failed",
                    # Legacy aliases publish on the new result-sink routing keys.
                    "result_delivery_requested": "result_sink.emit.requested",
                    "result_delivery_completed": "result_sink.emit.completed",
                    "result_delivery_failed": "result_sink.emit.failed",
                }[job.message_type]
            elif isinstance(job, DomainJobEnvelope):
                routing_key = job.job_type
            else:
                routing_key = "unknown"
            await exchange.publish(message, routing_key=routing_key)
        finally:
            await connection.close()

    async def status(self) -> dict:
        return {
            "backend": "rabbitmq",
            "exchange": self.settings.rabbitmq.job_exchange,
            "url": self.settings.rabbitmq.url,
        }
