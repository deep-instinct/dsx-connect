from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn

from dsx_connect_ng.api.routes.control_plane import router as control_plane_router
from dsx_connect_ng.api.routes.execution import router as execution_router
from dsx_connect_ng.api.routes.health import router as health_router
from dsx_connect_ng.api.routes.ui import router as ui_router
from dsx_connect_ng.config import settings
from dsx_connect_ng.control_plane.bootstrap import bootstrap_control_plane
from dsx_connect_ng.jobs.bootstrap import bootstrap_job_bus, bootstrap_job_service
from dsx_connect_ng.version import DSX_CONNECT_VERSION

_UI_ASSETS_DIR = Path(__file__).resolve().parent / "ui" / "assets"


def create_app() -> FastAPI:
    app = FastAPI(
        title="DSX-Connect",
        version=DSX_CONNECT_VERSION,
        summary="Control-plane-first implementation for DSX-Connect v2.",
    )
    bootstrap = bootstrap_control_plane()
    job_bus_bootstrap = bootstrap_job_bus()
    job_service_bootstrap = bootstrap_job_service(bootstrap, job_bus_bootstrap)
    app.state.control_plane_bootstrap = bootstrap
    app.state.control_plane_service = bootstrap.service
    app.state.job_bus_bootstrap = job_bus_bootstrap
    app.state.job_bus = job_bus_bootstrap.bus
    app.state.job_service_bootstrap = job_service_bootstrap
    app.state.job_service = job_service_bootstrap.service
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(control_plane_router, prefix=settings.api_prefix)
    app.include_router(execution_router, prefix=settings.api_prefix)
    app.mount(
        f"{settings.api_prefix}/ui-static",
        StaticFiles(directory=_UI_ASSETS_DIR),
        name="dsx-connect-ui-assets",
    )
    app.include_router(ui_router, prefix=settings.api_prefix)
    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "dsx_connect_ng.app:app",
        host="127.0.0.1",
        port=8091,
        reload=False,
    )
