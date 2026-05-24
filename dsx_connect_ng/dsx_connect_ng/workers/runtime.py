from typing import Any

from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.bootstrap import bootstrap_control_plane
from dsx_connect_ng.jobs.bootstrap import bootstrap_job_bus, bootstrap_job_service
from dsx_connect_ng.jobs.service import JobService
from dsx_connect_ng.jobs.topology import rabbitmq_topology_summary


def worker_runtime_summary() -> dict:
    return {
        "transport": "rabbitmq",
        "topology": rabbitmq_topology_summary(settings),
        "reader_mode": "worker_hosted",
    }


def build_job_service() -> tuple[JobService, dict[str, Any]]:
    control_plane = bootstrap_control_plane()
    job_bus = bootstrap_job_bus()
    job_service = bootstrap_job_service(control_plane, job_bus)
    summary = {
        "control_plane_backend": control_plane.backend,
        "control_plane_detail": control_plane.detail,
        "job_bus_backend": job_bus.backend,
        "job_bus_detail": job_bus.detail,
        "job_repository_backend": job_service.backend,
        "job_repository_detail": job_service.detail,
    }
    return job_service.service, summary
