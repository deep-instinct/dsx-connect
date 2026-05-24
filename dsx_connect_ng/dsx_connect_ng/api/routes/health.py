from fastapi import APIRouter

from dsx_connect_ng.config import settings
from dsx_connect_ng.jobs.topology import rabbitmq_topology_summary

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
    }


@router.get("/architecture")
async def architecture_status() -> dict:
    return {
        "service": settings.service_name,
        "separation_rules": {
            "imports_legacy_dsx_connect": False,
            "shared_legacy_tables": False,
            "legacy_preview_routes_reused": False,
        },
        "control_plane": {
            "enabled": settings.features.enable_control_plane,
            "postgres_url": settings.postgres.url,
            "auto_apply_schema": settings.postgres.auto_apply_schema,
        },
        "scope_engine": {
            "enabled": settings.features.enable_scope_engine,
            "ownership": "core",
        },
        "jobs": {
            "enabled": settings.features.enable_job_orchestration,
            "transport": "rabbitmq",
            "topology": rabbitmq_topology_summary(settings),
        },
        "read_path": {
            "mode": "worker_hosted_readers",
            "connector_callback_read_target": False,
        },
    }
