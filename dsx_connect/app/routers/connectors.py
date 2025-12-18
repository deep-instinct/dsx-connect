
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Request, Path, HTTPException, Depends, status
from starlette.responses import JSONResponse, Response

from dsx_connect.connectors import registration
from dsx_connect.connectors.client import get_connector_client, \
    get_async_connector_client  # ← new auth-aware async client
from dsx_connect.connectors.registry import ConnectorsRegistry
from shared.models.connector_models import ConnectorInstanceModel
from shared.dsx_logging import dsx_logging
from shared.models.status_responses import StatusResponse, StatusResponseEnum

from shared.routes import (
    API_PREFIX_V1,
    DSXConnectAPI,
    ConnectorPath,
    ConnectorAPI,
    route_name,
    Action,
    route_path,
)
from dsx_connect.app.auth_jwt import (
    auth_enabled,
    verify_enrollment_token,
    issue_access_token,
    enrollment_token_from_request,
    require_connector_bearer,
)
from dsx_connect.app.auth_tokens import issue_access_token_opaque
from dsx_connect.app.hmac_provision import ensure_hmac_for_connector, get_hmac_for_connector
from dsx_connect.app.auth_hmac_inbound import require_dsx_hmac_inbound

# Make sure prefix starts with "/"
router = APIRouter(prefix=route_path(API_PREFIX_V1))


def get_registry(request: Request) -> Optional[ConnectorsRegistry]:
    return getattr(request.app.state, "registry", None)

def get_redis(request: Request):
    # wherever you stash the async Redis client at startup
    return getattr(request.app.state, "redis", None)

async def _lookup(
        registry: Optional[ConnectorsRegistry],
        request: Request,
        connector_uuid: UUID,
) -> Optional[ConnectorInstanceModel]:
    if registry is not None:
        model = await registry.get(connector_uuid)  # async
        # Enrich with per-connector HMAC for outbound calls (in-memory attrs)
        try:
            if model is not None and auth_enabled():
                rds = getattr(request.app.state, "redis", None)
                kid, sec = await get_hmac_for_connector(rds, str(model.uuid))
                if kid and sec:
                    setattr(model, "hmac_key_id", kid)
                    setattr(model, "hmac_secret", sec)
        except Exception:
            pass
        return model
    lst: list[ConnectorInstanceModel] = getattr(request.app.state, "connectors", [])
    return next((c for c in lst if c.uuid == connector_uuid), None)



# Register connector (idempotent)
@router.post(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.REGISTER_CONNECTORS),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.REGISTER_CONNECTORS, Action.REGISTER),
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
)
async def register_connector(
        conn: ConnectorInstanceModel,
        request: Request,
        response: Response,
        registry: ConnectorsRegistry | None = Depends(get_registry),
        r = Depends(get_redis),
):
    # Enforce enrollment token when auth is enabled
    try:
        if auth_enabled():
            enroll = enrollment_token_from_request(request)
            if not verify_enrollment_token(enroll):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_enrollment_token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_enrollment_token")
    ok, reg_status = await registration.register_or_refresh_connector(request, conn)
    if not ok:
        # keep returning 503 so connectors back off when Redis truly down
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="registry_unavailable")

    # optional: warm local cache immediately (pub/sub will also upsert)
    try:
        if registry is not None:
            await registry.upsert(conn)
    except Exception:
        pass

        # Dynamically set 201 vs 200, while still returning a validated model
    response.status_code = status.HTTP_201_CREATED if reg_status == "registered" else status.HTTP_200_OK

    # If auth is enabled and an enrollment token is provided, include an access token and per-connector HMAC creds
    token_payload = None
    hmac_payload = None
    try:
        if auth_enabled():
            enroll = request.headers.get("X-Enrollment-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if verify_enrollment_token(enroll):
                # Opaque access token (preferred)
                try:
                    rds = getattr(request.app.state, "redis", None)
                    tok, expires_in = await issue_access_token_opaque(rds, str(conn.uuid) if conn.uuid else None, ttl_seconds=600)
                    token_payload = {"access_token": tok, "token_type": "Bearer", "expires_in": expires_in}
                except Exception:
                    token_payload = issue_access_token(connector_uuid=str(conn.uuid) if conn.uuid else None)
                # Ensure per-connector HMAC creds are provisioned
                try:
                    rds = getattr(request.app.state, "redis", None)
                    kid, sec = await ensure_hmac_for_connector(rds, str(conn.uuid))
                    if kid and sec:
                        hmac_payload = {"hmac_key_id": kid, "hmac_secret": sec}
                except Exception:
                    pass
    except Exception:
        token_payload = None

    base = {
        "status": StatusResponseEnum.SUCCESS,
        "message": str(reg_status),
        "description": f"{conn.name} ({conn.uuid}) @ {conn.url}",
    }
    try:
        if getattr(conn, "uuid", None):
            base["connector_uuid"] = str(conn.uuid)
    except Exception:
        pass
    if token_payload:
        base.update(token_payload)
    if hmac_payload:
        base.update(hmac_payload)
    return base


@router.delete(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.UNREGISTER_CONNECTORS),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.UNREGISTER_CONNECTORS, Action.UNREGISTER),
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unregister_connector(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry: ConnectorsRegistry | None = Depends(get_registry),
        r = Depends(get_redis),
):
    # Auth: require either enrollment token or inbound HMAC when enabled
    if auth_enabled():
        ok = False
        try:
            # Enrollment token path
            enroll = enrollment_token_from_request(request)
            if verify_enrollment_token(enroll):
                ok = True
        except Exception:
            pass
        if not ok:
            # Try HMAC
            try:
                from dsx_connect.app.auth_hmac_inbound import require_dsx_hmac_inbound
                await require_dsx_hmac_inbound(request)
                ok = True
            except HTTPException as e:
                if e.status_code != status.HTTP_401_UNAUTHORIZED:
                    raise
        if not ok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    # If Redis is down, tell the caller to back off
    if r is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="registry_unavailable")

    # (Optional) grab name for nicer event payloads
    name = None
    if registry is not None:
        try:
            m = await registry.get(connector_uuid)
            name = getattr(m, "name", None)
        except Exception:
            pass

    # Unregister in Redis (idempotent)
    try:
        ok = await registration.unregister_connector(request, connector_uuid, name=name)
        if not ok:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="registry_unavailable")
    except HTTPException as e:
        dsx_logging.warn(f"Failed to unregister connector {connector_uuid}: {e}")
        raise
    except Exception as e:
        # Treat as not found vs server error depending on preference; here we surface 500
        dsx_logging.warn(f"Failed to unregister connector {connector_uuid}: {e}")
        raise HTTPException(status_code=500, detail=f"unregister_failed: {e}")

    # Best-effort local cache cleanup (pub/sub will also handle)
    if registry is not None:
        try:
            await registry.remove(connector_uuid)
        except Exception:
            pass

    # 204 No Content
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# List registered connectors
@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS, Action.LIST),
    response_model=list[ConnectorInstanceModel],
    status_code=status.HTTP_200_OK,
)
async def list_connectors(request: Request, registry=Depends(get_registry)):
    # 1) Try cache first
    if registry is not None:
        items = await registry.list()          # cached view
        if items:                              # happy path
            return items
        dsx_logging.debug("ConnectorsRegistry cache empty; falling back to Redis scan")
    return []

# Outbound HMAC auth check (dsx-connect -> connector)
@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, "auth_check/{connector_uuid}"),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS, Action.HEALTH),
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
)
async def connector_auth_check(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    """Verify dsx-connect can call a connector private endpoint using DSX-HMAC.

    Calls the connector's CONFIG endpoint (which is HMAC-protected when enabled) and
    returns SUCCESS if the connector accepts the signed request (non-401).
    """
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")
    try:
        async with get_async_connector_client(conn) as client:
            # CONFIG is a lightweight private endpoint guarded by HMAC on the connector
            resp = await client.get(ConnectorAPI.CONFIG)
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="unauthorized: hmac_rejected")
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="auth_ok", description="HMAC verified")
    except HTTPException:
        raise
    except Exception as e:
        # Non-auth errors: surface as 502 to distinguish from 401
        raise HTTPException(status_code=502, detail=f"auth_check_failed: {e}")


# Lightweight connector state (KV) for stateless connectors (stored in Redis)
@router.put(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, "state/{connector_uuid}/{ns}/{key}"),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS, Action.UPDATE),
    status_code=status.HTTP_204_NO_CONTENT,
)
async def connector_state_put(
        request: Request,
        connector_uuid: UUID = Path(...),
        ns: str = Path(...),
        key: str = Path(...),
):
    # Require inbound HMAC from connector
    await require_dsx_hmac_inbound(request)
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="registry_unavailable")
    try:
        body = await request.body()
        # small bytes payload; store as is
        k = f"dsxconnect:connector_state:{connector_uuid}:{ns}:{key}"
        await r.set(k, body.decode() if body else "", ex=None)
        return Response(status_code=204)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"state_put_failed: {e}")


@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, "state/{connector_uuid}/{ns}/{key}"),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS, Action.GET),
    status_code=status.HTTP_200_OK,
)
async def connector_state_get(
        request: Request,
        connector_uuid: UUID = Path(...),
        ns: str = Path(...),
        key: str = Path(...),
):
    # Require inbound HMAC from connector
    await require_dsx_hmac_inbound(request)
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="registry_unavailable")
    try:
        k = f"dsxconnect:connector_state:{connector_uuid}:{ns}:{key}"
        val = await r.get(k)
        return JSONResponse({"value": val})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"state_get_failed: {e}")

# Trigger a full scan on a connector (async command)
@router.post(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_FULLSCAN_CONNECTOR),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_FULLSCAN_CONNECTOR, Action.FULLSCAN),
    response_model=StatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_fullscan(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
        response: Response = None,
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector registered with UUID={connector_uuid}")

    try:
        # Forward optional query params (e.g., limit=N for sample scan)
        params = dict(request.query_params)
        # Ensure a job_id is present so all enqueued items share it
        if 'job_id' not in params or not params['job_id']:
            import uuid as _uuid
            params['job_id'] = str(_uuid.uuid4())

        # Feature-flagged preflight estimate; if exact, store expected_total on the job
        try:
            from dsx_connect.config import get_config
            cfg = get_config()
            est = None
            if getattr(cfg.features, 'enable_estimate_preflight', False):
                async with get_async_connector_client(conn) as client:
                    est_resp = await client.get(ConnectorAPI.ESTIMATE)
                    est = est_resp.json() if est_resp.status_code == 200 else None
                r = getattr(request.app.state, "redis", None)
                if r is not None:
                    key = f"dsxconnect:job:{params['job_id']}"
                    if isinstance(est, dict) and est.get('confidence') == 'exact' and isinstance(est.get('count'), int):
                        await r.hset(key, mapping={'expected_total': str(est['count']), 'status': 'running'})
                    await r.expire(key, 7 * 24 * 3600)
        except Exception:
            pass

        async with get_async_connector_client(conn) as client:
            conn_resp = await client.post(ConnectorAPI.FULL_SCAN, params=params)
            conn_resp.raise_for_status()
            data = conn_resp.json()
        # Set job id header for client convenience
        try:
            if response is not None:
                response.headers['X-Job-Id'] = params['job_id']
        except Exception:
            pass
        if isinstance(data, dict):
            # Ensure response mentions job id for easy display
            try:
                sr = StatusResponse(**data)
                if params.get('job_id') and (not sr.description or 'job_id=' not in sr.description):
                    sr.description = (sr.description + ' | ' if sr.description else '') + f"job_id={params['job_id']}"
                return sr
            except Exception:
                pass
        return StatusResponse(status=StatusResponseEnum.SUCCESS,
                              message="full scan triggered",
                              description=f"job_id={params['job_id']}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        # Log connection issues without stack trace - these are expected when services are down
        dsx_logging.warning(f"Connector FULLSCAN call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        # Log unexpected errors with stack trace for debugging
        dsx_logging.error(f"Unexpected error in connector FULLSCAN call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_REPOCHECK_CONNECTOR),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_REPOCHECK_CONNECTOR, Action.HEALTH),
    response_model=StatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_connector_repo_check(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    try:
        # Forward query params (e.g., preview=N)
        params = dict(request.query_params)
        async with get_async_connector_client(conn) as client:
            response = await client.get(ConnectorAPI.REPO_CHECK, params=params)
            response.raise_for_status()
            data = response.json()
        return StatusResponse(**data) if isinstance(data, dict) else StatusResponse(
            status=StatusResponseEnum.SUCCESS, message="repo_check"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        dsx_logging.warning(f"Connector REPO_CHECK call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        dsx_logging.error(f"Unexpected error in connector REPO_CHECK call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


# Estimate (proxy GET)
@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, "estimate/{connector_uuid}"),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.LIST_CONNECTORS, Action.STATS),
    status_code=status.HTTP_200_OK,
)
async def get_connector_estimate(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    try:
        async with get_async_connector_client(conn) as client:
            response = await client.get(ConnectorAPI.ESTIMATE)
            response.raise_for_status()
            data = response.json()
        # normalize shape
        if isinstance(data, dict) and "confidence" in data and "count" in data:
            return data
        return {"count": None, "confidence": "unknown"}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        dsx_logging.warning(f"Connector ESTIMATE call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        dsx_logging.error(f"Unexpected error in connector ESTIMATE call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

# Fetch connector config (proxy GET)
@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_CONFIG_CONNECTOR),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_CONFIG_CONNECTOR, Action.CONFIG),
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
async def get_connector_config(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    try:
        async with get_async_connector_client(conn) as client:
            response = await client.get(ConnectorAPI.CONFIG)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        # Log connection issues without stack trace - these are expected when services are down
        dsx_logging.warning(f"Connector CONFIG call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        # Log unexpected errors with stack trace for debugging
        dsx_logging.error(f"Unexpected error in connector CONFIG call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_HEALTHZ_CONNECTOR),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_HEALTHZ_CONNECTOR, Action.HEALTH),
    status_code=status.HTTP_200_OK,
)
async def get_connector_healthz(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    try:
        async with get_async_connector_client(conn) as client:
            response = await client.get(ConnectorAPI.HEALTHZ)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        # Log connection issues without stack trace - these are expected when services are down
        dsx_logging.debug(f"Connector HEALTHZ call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        # Log unexpected errors with stack trace for debugging
        dsx_logging.error(f"Unexpected error in connector HEALTHZ call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


# Readyz (proxy GET)
@router.get(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_READYZ_CONNECTOR),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.TRIGGER_READYZ_CONNECTOR, Action.READY),
    status_code=status.HTTP_200_OK,
)
async def get_connector_readyz(
        request: Request,
        connector_uuid: UUID = Path(..., description="UUID of the connector"),
        registry=Depends(get_registry),
):
    conn = await _lookup(registry, request, connector_uuid)
    if not conn:
        raise HTTPException(status_code=404, detail=f"No connector found with UUID={connector_uuid}")

    try:
        async with get_async_connector_client(conn) as client:
            response = await client.get(ConnectorAPI.READYZ)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        # Log connection issues without stack trace - these are expected when services are down
        dsx_logging.warning(f"Connector READYZ call failed - service unavailable at {conn.url}: {type(e).__name__}")
        raise HTTPException(status_code=502, detail=f"Connector service unavailable: {type(e).__name__}")
    except Exception as e:
        # Log unexpected errors with stack trace for debugging
        dsx_logging.error(f"Unexpected error in connector READYZ call: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


# Mint a short-lived access token given a valid enrollment token
@router.post(
    route_path(DSXConnectAPI.CONNECTORS_PREFIX, "token"),
    name=route_name(DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.REGISTER_CONNECTORS, Action.REGISTER),
    status_code=status.HTTP_200_OK,
)
async def mint_connector_token(request: Request):
    from dsx_connect.config import get_auth_config
    cfg = get_auth_config()
    if not auth_enabled():
        raise HTTPException(status_code=400, detail="auth_disabled")
    enroll = request.headers.get("X-Enrollment-Token") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not verify_enrollment_token(enroll):
        raise HTTPException(status_code=401, detail="invalid_enrollment_token")
    # Optionally accept connector uuid in query for sub claim; otherwise omit
    try:
        params = dict(request.query_params)
        sub = params.get("connector_uuid")
    except Exception:
        sub = None
    try:
        rds = getattr(request.app.state, "redis", None)
        tok, expires_in = await issue_access_token_opaque(rds, sub, ttl_seconds=600)
        payload = {"access_token": tok, "token_type": "Bearer", "expires_in": expires_in}
    except Exception:
        payload = issue_access_token(connector_uuid=sub)
    if sub:
        payload["connector_uuid"] = sub
    return payload
