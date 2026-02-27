import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
import httpx

from shared.models.connector_models import (
    ScanRequestModel,
    ConnectorInstanceModel,
    ItemActionEnum,
)
from shared.dsx_logging import dsx_logging
from shared.routes import API_PREFIX_V1, DSXConnectAPI, Action, route_name, route_path, ConnectorAPI

from dsx_connect.taskworkers.celery_app import celery_app
from dsx_connect.taskworkers.names import Tasks, Queues
from dsx_connect.connectors.registry import ConnectorsRegistry
from dsx_connect.connectors.client import get_connector_client
from dsx_connect.database.database_factory import database_scan_results_factory
from dsx_connect.config import get_config
from dsx_connect.database.dianna_siem_index_redis import DiannaSiemIndexRedis


router = APIRouter(prefix=route_path(API_PREFIX_V1))
_results_database = database_scan_results_factory(
    database_loc=get_config().results_database.loc,
    retain=get_config().results_database.retain,
)
_dianna_index = DiannaSiemIndexRedis(
    database_loc=get_config().dianna.index_database_loc,
    retain_days=get_config().dianna.index_retain_days,
)


def get_registry(request: Request) -> Optional[ConnectorsRegistry]:
    return getattr(request.app.state, "registry", None)


class AnalyzeRequest(BaseModel):
    location: str
    metainfo: Optional[str] = None
    archive_password: Optional[str] = None


class AnalyzeFromSiemRequest(BaseModel):
    # Preferred SIEM correlation key: root scan task id from malicious event.
    scan_request_task_id: Optional[str] = None
    # Optional explicit connector/file hints (used when task id lookup is unavailable).
    connector_uuid: Optional[UUID] = None
    connector_url: Optional[str] = None
    location: Optional[str] = None
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


async def _lookup_by_url(
        registry: Optional[ConnectorsRegistry],
        request: Request,
        connector_url: str,
) -> Optional[ConnectorInstanceModel]:
    if registry is not None:
        try:
            lst = await registry.list()
            return next((c for c in lst if str(getattr(c, "url", "")) == connector_url), None)
        except Exception:
            pass
    lst: list[ConnectorInstanceModel] = getattr(request.app.state, "connectors", [])
    return next((c for c in lst if str(getattr(c, "url", "")) == connector_url), None)


def _probe_read_via_connector(scan_req: ScanRequestModel) -> tuple[bool, str]:
    target = scan_req.connector or scan_req.connector_url
    try:
        with get_connector_client(target) as client:
            response = client.post(ConnectorAPI.READ_FILE, json_body=jsonable_encoder(scan_req))
        status_code = response.status_code
        ok = 200 <= status_code < 300
        try:
            response.close()
        except Exception:
            pass
        return ok, f"http_{status_code}"
    except httpx.HTTPError:
        return False, "http_error"
    except Exception as e:
        return False, f"exception:{e.__class__.__name__}"


def _quarantine_candidate_paths(location: str, metainfo: str, connector: ConnectorInstanceModel) -> list[str]:
    candidates: list[str] = []
    if not location:
        return candidates
    candidates.append(location)

    action = getattr(connector, "item_action", None)
    qdir = (getattr(connector, "item_action_move_metainfo", None) or "").strip()
    if action in {ItemActionEnum.MOVE, ItemActionEnum.MOVE_TAG} and qdir:
        base1 = os.path.basename(location)
        base2 = os.path.basename(metainfo or "")
        for base in [base1, base2]:
            if not base:
                continue
            qp = os.path.join(qdir, base)
            if qp not in candidates:
                candidates.append(qp)
    return candidates


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
    return {
        "status": "accepted",
        "dianna_analysis_task_id": async_result.id,
        "task_id": async_result.id,  # backward compatibility
    }


@router.post(
    route_path(DSXConnectAPI.DIANNA_PREFIX, "analyze-from-siem"),
    name=route_name(DSXConnectAPI.DIANNA_PREFIX, "analyze-from-siem", Action.CREATE),
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_dianna_analysis_from_siem(
        request: Request,
        payload: AnalyzeFromSiemRequest,
        registry=Depends(get_registry),
):
    scan_req_from_result: Optional[ScanRequestModel] = None
    scan_req_from_index: Optional[ScanRequestModel] = None
    if payload.scan_request_task_id:
        # Preferred: dedicated malicious index with longer retention.
        try:
            rec = _dianna_index.get(payload.scan_request_task_id) or {}
        except Exception:
            rec = {}
        if rec:
            connector = None
            conn_uuid_raw = rec.get("connector_uuid")
            conn_url_raw = rec.get("connector_url")
            if conn_uuid_raw:
                try:
                    connector = await _lookup(registry, request, UUID(str(conn_uuid_raw)))
                except Exception:
                    connector = None
            if connector is None and conn_url_raw:
                connector = await _lookup_by_url(registry, request, str(conn_url_raw))
            if connector is not None and rec.get("location"):
                scan_req_from_index = ScanRequestModel(
                    connector=connector,
                    connector_url=connector.url,
                    location=str(rec.get("location")),
                    metainfo=str(rec.get("metainfo") or rec.get("location")),
                )

    if payload.scan_request_task_id and scan_req_from_index is None:
        try:
            rows = _results_database.find("scan_request_task_id", payload.scan_request_task_id) or []
        except Exception:
            rows = []
        if rows:
            scan_req_from_result = getattr(rows[0], "scan_request", None)

    connector = None
    location = payload.location
    metainfo = payload.metainfo

    if scan_req_from_index is not None:
        connector = scan_req_from_index.connector
        location = location or scan_req_from_index.location
        metainfo = metainfo or scan_req_from_index.metainfo
        if payload.connector_uuid and connector and connector.uuid and payload.connector_uuid != connector.uuid:
            raise HTTPException(status_code=409, detail="connector_uuid_mismatch_for_scan_request_task_id")
    elif scan_req_from_result is not None:
        connector = scan_req_from_result.connector
        location = location or scan_req_from_result.location
        metainfo = metainfo or scan_req_from_result.metainfo
        if payload.connector_uuid and connector and connector.uuid and payload.connector_uuid != connector.uuid:
            raise HTTPException(status_code=409, detail="connector_uuid_mismatch_for_scan_request_task_id")
        # Refresh connector from live registry when possible (stored scan_result connector may be stale).
        try:
            if connector and connector.uuid:
                live = await _lookup(registry, request, connector.uuid)
                if live is not None:
                    connector = live
        except Exception:
            pass

    if connector is None and payload.connector_uuid:
        connector = await _lookup(registry, request, payload.connector_uuid)
    if connector is None and payload.connector_url:
        connector = await _lookup_by_url(registry, request, payload.connector_url)
    if connector is None and scan_req_from_result is not None and getattr(scan_req_from_result, "connector_url", None):
        connector = await _lookup_by_url(registry, request, scan_req_from_result.connector_url)

    if connector is None:
        raise HTTPException(
            status_code=404,
            detail="connector_not_found: provide scan_request_task_id or valid connector_uuid/connector_url",
        )
    if not location:
        raise HTTPException(
            status_code=400,
            detail="location_required: provide location or scan_request_task_id",
        )
    metainfo = metainfo or location

    # Resolve readable location: original first, then quarantine candidate if configured.
    candidate_locations = _quarantine_candidate_paths(location, metainfo, connector)
    resolved_location = None
    probe_results: list[str] = []
    for cand in candidate_locations:
        probe_req = ScanRequestModel(
            connector=connector,
            connector_url=connector.url,
            location=cand,
            metainfo=metainfo,
        )
        ok, detail = _probe_read_via_connector(probe_req)
        probe_results.append(f"{cand}=>{detail}")
        if ok:
            resolved_location = cand
            break

    if not resolved_location:
        msg = (
            f"file no longer exists - please check ITEM_ACTION configuration for "
            f"connector {connector.name}/{connector.uuid}; probes={'; '.join(probe_results)}"
        )
        raise HTTPException(status_code=409, detail=msg)

    scan_req = ScanRequestModel(
        connector=connector,
        connector_url=connector.url,
        location=resolved_location,
        metainfo=metainfo,
    )
    async_result = celery_app.send_task(
        Tasks.DIANNA_ANALYZE,
        args=[scan_req.model_dump()],
        kwargs={"archive_password": payload.archive_password},
        queue=Queues.ANALYZE,
    )
    dsx_logging.info(
        f"[dianna] SIEM enqueued analysis {async_result.id} for {resolved_location} "
        f"(connector={connector.uuid})"
    )

    try:
        notifiers = getattr(request.app.state, 'notifiers', None)
        if notifiers is not None:
            event = {
                "type": "dianna_enqueued",
                "task_id": async_result.id,
                "connector_uuid": str(connector.uuid) if connector.uuid else None,
                "location": resolved_location,
                "metainfo": metainfo,
                "source": "siem",
            }
            await notifiers.publish_scan_results_async(event)
    except Exception:
        pass

    return {
        "status": "accepted",
        "dianna_analysis_task_id": async_result.id,
        "task_id": async_result.id,  # backward compatibility
        "connector_uuid": str(connector.uuid) if connector.uuid else None,
        "location_requested": location,
        "location_resolved": resolved_location,
        "used_quarantine_fallback": resolved_location != location,
    }


@router.get(
    route_path(DSXConnectAPI.DIANNA_PREFIX, "result", "{analysis_id}"),
    name=route_name(DSXConnectAPI.DIANNA_PREFIX, "result", Action.GET),
    status_code=status.HTTP_200_OK,
)
async def get_dianna_result(analysis_id: str):
    return _fetch_dianna_result_payload(analysis_id)


def _fetch_dianna_result_payload(analysis_id: str) -> dict:
    cfg = get_config().dianna
    url = cfg.management_url.rstrip("/") + f"/api/v1/dianna/analysisResult/{analysis_id}"
    headers = {"accept": "application/json"}
    if cfg.api_token:
        headers["Authorization"] = cfg.api_token
    timeout = httpx.Timeout(cfg.timeout)

    try:
        with httpx.Client(timeout=timeout, verify=(cfg.ca_bundle or cfg.verify_tls)) as client:
            r = client.get(url, headers=headers)
            r.raise_for_status()
            payload = r.json() if r.content else {}
            return {
                "status": "success",
                "analysis_id": analysis_id,
                "source": "dianna",
                "result": payload,
            }
    except httpx.HTTPStatusError as e:
        code = getattr(e.response, "status_code", 502)
        detail = f"dianna_http_{code}"
        try:
            body = e.response.json() if e.response is not None else {}
            if isinstance(body, dict) and body:
                detail = {"error": detail, "upstream": body}
        except Exception:
            pass
        raise HTTPException(status_code=code, detail=detail) from e
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
        raise HTTPException(status_code=503, detail=f"dianna_unavailable: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"dianna_result_lookup_failed: {e}") from e


@router.get(
    route_path(DSXConnectAPI.DIANNA_PREFIX, "result", "by-task", "{dianna_analysis_task_id}"),
    name=route_name(DSXConnectAPI.DIANNA_PREFIX, "result-by-task", Action.GET),
    status_code=status.HTTP_200_OK,
)
async def get_dianna_result_by_task_id(dianna_analysis_task_id: str):
    task = celery_app.AsyncResult(dianna_analysis_task_id)
    state = str(getattr(task, "state", "UNKNOWN")).upper()

    if state in {"PENDING", "RECEIVED", "STARTED", "RETRY"}:
        return {
            "status": "processing",
            "task_state": state,
            "dianna_analysis_task_id": dianna_analysis_task_id,
        }

    if state in {"FAILURE", "REVOKED"}:
        detail = str(getattr(task, "result", "task_failed"))
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "task_state": state,
                "dianna_analysis_task_id": dianna_analysis_task_id,
                "message": detail,
            },
        )

    # SUCCESS: task result should carry DIANNA identifier (analysisId or upload_id)
    result_value = getattr(task, "result", None)
    identifier = None
    if result_value is not None:
        s = str(result_value).strip()
        if s and s.upper() != "OK":
            identifier = s

    if not identifier:
        return {
            "status": "accepted",
            "task_state": state,
            "dianna_analysis_task_id": dianna_analysis_task_id,
            "message": "task completed but no analysis identifier is available",
        }

    payload = _fetch_dianna_result_payload(identifier)
    payload["dianna_analysis_task_id"] = dianna_analysis_task_id
    payload["resolved_from"] = "task_result"
    return payload
