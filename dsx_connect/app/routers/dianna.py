from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel

from shared.models.connector_models import ScanRequestModel, ConnectorInstanceModel
from shared.dsx_logging import dsx_logging
from shared.routes import API_PREFIX_V1, DSXConnectAPI, Action, route_name, route_path

from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues
from dsx_connect.connectors.registry import ConnectorsRegistry


router = APIRouter(prefix=route_path(API_PREFIX_V1))


def get_registry(request: Request) -> Optional[ConnectorsRegistry]:
    return getattr(request.app.state, "registry", None)


class AnalyzeRequest(BaseModel):
    location: str
    metainfo: Optional[str] = None
    archive_password: Optional[str] = None


async def _lookup(
        registry: Optional[ConnectorsRegistry],
        request: Request,
        connector_uuid: UUID,
) -> Optional[ConnectorInstanceModel]:
    if registry is not None:
        return await registry.get(connector_uuid)
    lst: list[ConnectorInstanceModel] = getattr(request.app.state, "connectors", [])
    return next((c for c in lst if c.uuid == connector_uuid), None)


@router.post(
    route_path(DSXConnectAPI.DIANNA_PREFIX, "analyze", "{connector_uuid}"),
    name=route_name(DSXConnectAPI.DIANNA_PREFIX, "analyze", Action.CREATE),
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_dianna_analysis(
        request: Request,
        payload: AnalyzeRequest,
        connector_uuid: UUID = Path(..., description="UUID of the connector that can read the file"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    scan_req = ScanRequestModel(
        connector=conn,
        connector_url=conn.url,
        location=payload.location,
        metainfo=payload.metainfo or payload.location,
    )

    async_result = celery_app.send_task(
        Tasks.DIANNA_ANALYZE,
        args=[scan_req.model_dump()],
        kwargs={"archive_password": payload.archive_password},
        queue=Queues.ANALYZE,
    )
    dsx_logging.info(f"[dianna] enqueued analysis {async_result.id} for {payload.location}")

    # Publish a lightweight SSE event for immediate UI feedback
    try:
        notifiers = getattr(request.app.state, 'notifiers', None)
        if notifiers is not None:
            event = {
                "type": "dianna_enqueued",
                "task_id": async_result.id,
                "connector_uuid": str(conn.uuid),
                "location": payload.location,
                "metainfo": payload.metainfo or payload.location,
            }
            await notifiers.publish_scan_results_async(event)
    except Exception:
        pass
    return {"status": "accepted", "task_id": async_result.id}
