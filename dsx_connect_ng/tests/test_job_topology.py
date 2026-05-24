import asyncio

from dsx_connect_ng.api.routes.execution import execution_topology
from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.topology import rabbitmq_topology_summary


def test_rabbitmq_topology_summary_exposes_retry_and_dlq_runtime() -> None:
    summary = rabbitmq_topology_summary(settings)

    assert summary["queues"]["scan"]["retry"] == "dsx.ng.scan.retry"
    assert summary["queues"]["scan"]["dlq"] == "dsx.ng.scan.dlq"
    assert summary["queues"]["result_sink"]["work"] == "dsx.ng.result_sink"
    assert summary["retry_runtime"]["header"] == "x-dsx-retry-attempt"
    assert summary["retry_runtime"]["max_attempts"] == settings.rabbitmq.retry_max_attempts
    assert summary["retry_runtime"]["delay_ms"] == settings.rabbitmq.retry_delay_ms


def test_execution_topology_endpoint_is_read_only_configuration_view() -> None:
    payload = asyncio.run(execution_topology())

    assert payload["surface"] == "execution_topology"
    assert payload["transport"] == settings.job_bus_backend
    assert payload["topology"]["queues"]["dianna"]["dlq"] == "dsx.ng.dianna.dlq"
    assert "configured queue topology only" in payload["notes"][0]
    assert "Manual DLQ replay is not implemented yet." in payload["notes"]
