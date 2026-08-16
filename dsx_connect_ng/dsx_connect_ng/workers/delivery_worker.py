from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config
from dsx_connect_ng.control_plane.models import utcnow
from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.contracts import MessageEnvelope, ResultSinkEmitRequested
from dsx_connect_ng.jobs.models import DeliveryResult, DeliveryStageUpdateRequest
from dsx_connect_ng.readers.proxy import ConnectorProxyRuntimeConfig
from dsx_connect_ng.result_sink.base import ResultSink
from dsx_connect_ng.result_sink.bootstrap import build_result_sink
from dsx_connect_ng.result_sink.models import ResultSinkEvent
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.workers.consumer import consume_queue
from dsx_connect_ng.workers.runtime import build_job_service


ResultSinkExecutor = Callable[[ResultSinkEmitRequested], Awaitable[DeliveryResult]]


def _split_gcs_path(value: str | None) -> tuple[str, str]:
    raw = str(value or "").strip()
    if raw.startswith("gs://"):
        raw = raw[5:]
    raw = raw.strip("/")
    if "/" not in raw:
        return raw, ""
    bucket, key = raw.split("/", 1)
    return bucket.strip(), key.strip("/")


def _gateway_gcs_target(request: ResultSinkEmitRequested) -> dict | None:
    target = request.delivery_target.delivery_target
    if target.get("type") != "gateway_destination":
        return None
    if str(target.get("platform") or "").lower() != "gcs":
        return None
    return target


def _content_source_locator(request: ResultSinkEmitRequested) -> str:
    content_source = request.final_result.get("contentSource") if isinstance(request.final_result, dict) else None
    if not isinstance(content_source, dict):
        raise RuntimeError("gateway GCS delivery requires contentSource metadata")
    if content_source.get("mode") != "cached":
        raise RuntimeError("gateway GCS delivery requires cached content source")
    locator = str(content_source.get("locator") or "").strip()
    if not locator:
        raise RuntimeError("gateway GCS delivery requires cached content locator")
    path = Path(locator)
    if not path.is_file():
        raise RuntimeError(f"gateway cached artifact not found: {locator}")
    return str(path)


def _delivery_proxy_config(service: JobService, request: ResultSinkEmitRequested) -> ConnectorProxyRuntimeConfig:
    if not request.integration_id:
        raise RuntimeError("gateway GCS delivery requires integration_id")
    integration = service.control_plane.get_integration_or_404(request.integration_id)
    runtime = parse_integration_runtime_config(integration.config)
    proxy = runtime.delivery.proxy if runtime.delivery and runtime.delivery.proxy else None
    endpoint_url = proxy.endpoint_url if proxy else None
    if not endpoint_url:
        instances = [
            instance
            for instance in service.control_plane.list_connector_instances(integration_id=request.integration_id)
            if instance.expires_at > utcnow() and instance.capabilities.get("write") is not False
        ]
        if instances:
            priority = {"healthy": 0, "degraded": 1, "unknown": 2, "unhealthy": 3}
            instance = sorted(instances, key=lambda item: priority.get(item.health, 99))[0]
            endpoint_url = f"{instance.base_url.rstrip('/')}/write_file"
    if not endpoint_url and proxy and proxy.base_url and proxy.connector_name:
        endpoint_url = f"{str(proxy.base_url).rstrip('/')}/{str(proxy.connector_name).strip('/')}/write_file"
    if not endpoint_url:
        raise RuntimeError("gateway GCS delivery requires integration delivery.proxy endpoint_url")
    return ConnectorProxyRuntimeConfig(
        endpoint_url=str(endpoint_url),
        auth_mode=str(proxy.auth_mode if proxy else "none"),
        header_name=proxy.header_name if proxy else None,
        header_value=proxy.header_value if proxy else None,
        hmac_key_id=proxy.hmac_key_id if proxy else None,
        hmac_secret=proxy.hmac_secret if proxy else None,
        timeout_seconds=float(proxy.timeout_seconds if proxy else 120.0),
    )


async def deliver_gateway_gcs(service: JobService, request: ResultSinkEmitRequested, target: dict) -> DeliveryResult:
    bucket, key = _split_gcs_path(target.get("path") or request.object_identity)
    if not bucket or not key:
        raise RuntimeError("gateway GCS delivery target must include bucket/object path")
    locator = _content_source_locator(request)
    config = _delivery_proxy_config(service, request)
    uri = f"gs://{bucket}/{key}"
    fields = {"bucket": bucket, "key": key, "destination": uri}
    headers: dict[str, str] = {}
    if config.auth_mode == "static_header":
        if not config.header_name or not config.header_value:
            raise RuntimeError("static_header auth requires header_name and header_value")
        headers[config.header_name] = config.header_value
    elif config.auth_mode == "dsx_hmac":
        raise RuntimeError("gateway GCS multipart delivery does not support dsx_hmac connector auth yet")
    timeout = httpx.Timeout(config.timeout_seconds, connect=min(config.timeout_seconds, 10.0))
    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(locator, "rb") as handle:
            response = await client.post(
                config.endpoint_url,
                data=fields,
                files={"file": (Path(locator).name, handle, "application/octet-stream")},
                headers=headers,
            )
    if response.status_code >= 400:
        raise RuntimeError(f"GCS connector delivery failed: http {response.status_code} {response.text}")
    payload = response.json()
    return DeliveryResult(
        destination=uri,
        outcome="delivered",
        externalReference=str(payload.get("uri") or uri),
        details={
            "worker": "gcs_gateway_delivery",
            "endpointUrl": config.endpoint_url,
            "bucket": bucket,
            "key": key,
            "connectorResponse": payload,
        },
    )


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


def build_result_sink_executor(service: JobService, sink: ResultSink) -> ResultSinkExecutor:
    async def execute(request: ResultSinkEmitRequested) -> DeliveryResult:
        gcs_target = _gateway_gcs_target(request)
        if gcs_target is not None:
            return await deliver_gateway_gcs(service, request, gcs_target)

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
        await process_result_sink_message(service, envelope, execute_result_sink=build_result_sink_executor(service, sink))

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
