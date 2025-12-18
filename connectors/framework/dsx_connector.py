import asyncio
import os
import sys
from pathlib import Path
import inspect
import contextvars
import uuid

from random import random
from typing import Any
from contextlib import asynccontextmanager
from fastapi.encoders import jsonable_encoder
from fastapi import FastAPI, APIRouter, Request, BackgroundTasks, Depends, HTTPException
from typing import Callable, Awaitable, Optional

from starlette.responses import StreamingResponse, JSONResponse, Response

from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ScanRequestModel, ConnectorInstanceModel, ConnectorStatusEnum, \
    ItemActionEnum
from shared.routes import DSXConnectAPI, ConnectorAPI, service_url, API_PREFIX_V1, ConnectorPath, ScanPath, route_path, \
     format_route
from shared.models.status_responses import StatusResponse, StatusResponseEnum, ItemActionStatusResponse
from shared.dsx_logging import dsx_logging
from connectors.framework.connector_id import get_or_create_connector_uuid
import httpx
from shared.routes import ConnectorAPI
from connectors.framework.auth_hmac import (
    require_dsx_hmac,
    reload_settings as reload_connector_auth_settings,
    auth_enabled as connector_auth_enabled,
)

# Context variable to propagate a scan job id during full_scan
_SCAN_JOB_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("scan_job_id", default=None)
_SCAN_ENQ_COUNTER: contextvars.ContextVar[int] = contextvars.ContextVar("scan_enq_counter", default=0)

# Legacy API key auth removed; HMAC verification now guards private routes when enabled.




# <end> API key config and validation

connector_api = None


def _sanitize_display_icon(raw: str | None) -> str | None:
    """Best-effort server-side validation for connector display_icon.

    - Limit length to 8KB
    - Allow only data URIs that begin with "data:image"
    - Allow raw <svg ...> markup but reject obvious dangerous patterns:
      script tags, event handlers, foreignObject, and http(s) external refs.
    Returns a safe string or None to drop.
    """
    if not raw:
        return None
    v = str(raw).strip()
    if not v:
        return None
    if len(v) > 8192:
        return None
    lower = v.lower()
    if lower.startswith("data:image"):
        return v
    if lower.startswith("<svg"):
        bad_tokens = (
            "<script", "onload=", "onerror=", "foreignobject", "<iframe",
            "xlink:href=\"http", "xlink:href='http", "href=\"http", "href='http",
            "url(http", "url(https"
        )
        if any(t in lower for t in bad_tokens):
            return None
        return v
    # Anything else is rejected
    return None


class DSXConnector:
    def __init__(self, connector_config: BaseConnectorConfig):
        self.connector_id = connector_config.name
        self.connector_config = connector_config

        # Ensure per-connector default data dir for UUID persistence in local/dev.
        # If DSXCONNECTOR_DATA_DIR is not set, derive it from the connector's config module path.
        try:
            if "DSXCONNECTOR_DATA_DIR" not in os.environ:
                mod_name = connector_config.__class__.__module__
                mod = sys.modules.get(mod_name)
                if mod and hasattr(mod, "__file__"):
                    cfg_path = Path(getattr(mod, "__file__")).resolve()
                    os.environ["DSXCONNECTOR_DATA_DIR"] = str(cfg_path.parent / "data")
        except Exception:
            pass

        uuid = get_or_create_connector_uuid()
        dsx_logging.debug(f"Logical connector {self.connector_id} using UUID: {uuid}")
        self.scan_request_count = 0
        # JWT enrollment + short-lived access token for dsx-connect auth
        self._enrollment_token: str | None = os.getenv("DSXCONNECT_ENROLLMENT_TOKEN") or None
        self._access_token: str | None = None
        self._access_expiry_ts: int | None = None

        # Refresh connector auth settings now that .env has been loaded
        try:
            reload_connector_auth_settings()
        except Exception:
            pass

        if self._enrollment_token:
            try:
                hmac_mode = connector_auth_enabled()
            except Exception:
                hmac_mode = os.getenv("DSXCONNECTOR_AUTH__ENABLED", "").strip().lower() in ("1", "true", "yes")
            if hmac_mode:
                dsx_logging.info("Connector authentication: enrollment token provided; DSX-HMAC verification enabled.")
            else:
                dsx_logging.info("Connector authentication: enrollment token provided; DSX-HMAC verification disabled (DSXCONNECTOR_AUTH__ENABLED=false).")
        else:
            dsx_logging.debug("Connector authentication: no enrollment token detected (DSXCONNECT_ENROLLMENT_TOKEN unset).")

        # clean up URL if needed
        self.dsx_connect_url = str(connector_config.dsx_connect_url).rstrip('/')

        self.connector_running_model = ConnectorInstanceModel(
            name=connector_config.name,
            display_name=(connector_config.display_name or None),
            display_icon=_sanitize_display_icon(getattr(connector_config, "display_icon", None) or None),
            uuid=uuid,
            # IMPORTANT: expose the connector under "<base>/<name>"
            url=f'{str(connector_config.connector_url).rstrip("/")}/{self.connector_id}',
            status=ConnectorStatusEnum.STARTING,
            item_action_move_metainfo=connector_config.item_action_move_metainfo,
            asset=connector_config.asset,
            asset_display_name=getattr(connector_config, 'asset_display_name', None) or None,
            filter=connector_config.filter
        )

        self.startup_handler: Optional[Callable[[ConnectorInstanceModel], Awaitable[ConnectorInstanceModel]]] = None
        self.shutdown_handler: Optional[Callable[[], Awaitable[None]]] = None

        self.full_scan_handler: Optional[Callable[[ScanRequestModel], StatusResponse]] = None
        self.item_action_handler: Optional[Callable[[ScanRequestModel], ItemActionStatusResponse]] = None
        self.read_file_handler: Optional[Callable[[ScanRequestModel], StreamingResponse | StatusResponse]] = None
        self.webhook_handler: Optional[Callable[[ScanRequestModel], StatusResponse]] = None

        # Allow sync OR async repo check that returns bool
        self.repo_check_connection_handler: Optional[Callable[[], bool | Awaitable[bool]]] = None

        self.config_handler: Optional[Callable[[ConnectorInstanceModel], Awaitable[ConnectorInstanceModel]]] = None
        # Optional preview provider: returns up to N sample item identifiers
        self.preview_provider: Optional[Callable[[int], Awaitable[list[str]]]] = None
        # Optional estimate provider: returns {"count": int|None, "confidence": "exact"|"unknown"}
        self.estimate_provider: Optional[Callable[[], Awaitable[dict]]] = None
        self._reg_retry_task: asyncio.Task | None = None
        # --- heartbeat (refreshes presence/TTL via register endpoint) ---
        self._hb_task: asyncio.Task | None = None
        self.HEARTBEAT_INTERVAL_SECONDS: int = 60  # <= half of server TTL (120s) is safe

        # httpx verify option for outbound calls to dsx-connect
        if not connector_config.verify_tls:
            self._httpx_verify = False
        elif connector_config.ca_bundle:
            self._httpx_verify = connector_config.ca_bundle
        else:
            self._httpx_verify = True

        # Initialize FastAPI app (lifespan handles registration + shutdown)
        self._initialize_app()

    def _dsx_hmac_headers(self, method: str, url: str, body: bytes | None) -> dict[str, str] | None:
        """Build DSX-HMAC headers for outbound calls when runtime credentials exist."""
        try:
            from connectors.framework.auth_hmac import build_outbound_auth_header
            header = build_outbound_auth_header(method, url, body)
        except Exception:
            header = None
        if header:
            return {"Authorization": header}
        return None

    # --------- FastAPI lifespan: startup/shutdown ----------
    def _build_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # ============ startup ============
            if self.startup_handler:
                # let plugin customize model (but NOT set READY)
                self.connector_running_model = await self.startup_handler(self.connector_running_model)

            # Try register once; if not READY, start background retry loop
            register_resp = await self.register_connector(self.connector_running_model)
            if register_resp.status == StatusResponseEnum.SUCCESS:
                # Check repo before READY
                repo_ok = await self._safe_repo_check_ok()
                if repo_ok:
                    self.connector_running_model.status = ConnectorStatusEnum.READY
                    dsx_logging.info("Connector is READY (registration + repo check OK).")
                    # Ensure heartbeat loop is running to refresh presence TTL in dsx-connect
                    self._start_heartbeat()
                else:
                    self.connector_running_model.status = ConnectorStatusEnum.STARTING
                    dsx_logging.info("Registration OK but repo check not ready; entering retry loop.")
                    self._start_retry_loop()
            else:
                self.connector_running_model.status = ConnectorStatusEnum.STARTING
                dsx_logging.warning(f"Connector registration failed: {register_resp.message}; entering retry loop.")
                self._start_retry_loop()

            # Hand control to FastAPI server
            yield

            # ============ shutdown ============
            # stop loops if running
            await self._cancel_heartbeat()
            await self._cancel_retry_loop()

            # unregister
            unregister_resp = await self.unregister_connector()
            if unregister_resp.status == StatusResponseEnum.SUCCESS:
                dsx_logging.info(f"Unregistered connector OK: {unregister_resp.message}")
            else:
                dsx_logging.warning(f"Connector unregistration failed: {unregister_resp.message}")

            # plugin shutdown
            if self.shutdown_handler:
                await self.shutdown_handler()

        docs_enabled = not connector_auth_enabled()
        return FastAPI(
            title=f"{self.connector_running_model.name} [dsx-connector]",
            description=f"API for dsx-connector: {self.connector_running_model.name} (UUID: {self.connector_running_model.uuid})",
            lifespan=lifespan,
            docs_url="/docs" if docs_enabled else None,
            redoc_url="/redoc" if docs_enabled else None,
            openapi_url="/openapi.json" if docs_enabled else None,
        )

        # Build router after app so we can re-use helper if needed

    def _initialize_app(self) -> None:
        """Create the FastAPI app and register routes (once per process)."""
        global connector_api
        connector_api = self._build_app()
        connector_api.include_router(DSXAConnectorRouter(self))

    # ----------------- decorator registrations -----------------

    def startup(self, func: Callable[[ConnectorInstanceModel], Awaitable[ConnectorInstanceModel]]):
        self.startup_handler = func
        return func

    def shutdown(self, func: Callable[[], Awaitable[None]]):
        self.shutdown_handler = func
        return func

    def full_scan(self, func: Callable[[ScanRequestModel], StatusResponse]):
        self.full_scan_handler = func
        return func

    def item_action(self, func: Callable[[ScanRequestModel], ItemActionStatusResponse]):
        self.item_action_handler = func
        return func

    def read_file(self, func: Callable[[ScanRequestModel], StreamingResponse | StatusResponse]):
        self.read_file_handler = func
        return func

    def repo_check(self, func: Callable[[], bool | Awaitable[bool]]):
        """Register a function to check repository connectivity (sync or async, must return bool)."""
        self.repo_check_connection_handler = func
        return func

    def webhook_event(self, func: Callable[[ScanRequestModel], StreamingResponse | StatusResponse]):
        self.webhook_handler = func
        return func

    def config(self, func: Callable[[ConnectorInstanceModel], Awaitable[ConnectorInstanceModel]]):
        self.config_handler = func
        return func

    def preview(self, func: Callable[[int], Awaitable[list[str]]]):
        """Register a function to return up to N preview items (strings)."""
        self.preview_provider = func
        return func

    def estimate(self, func: Callable[[], Awaitable[dict]]):
        """Register a function to return an estimate dict {count, confidence}."""
        self.estimate_provider = func
        return func

    # ----------------- helpers -----------------

    def _start_retry_loop(self):
        if self._reg_retry_task is None or self._reg_retry_task.done():
            self._reg_retry_task = asyncio.create_task(self._registration_retry_loop(), name="dsxconn-reg-retry")

    async def _cancel_retry_loop(self):
        task = self._reg_retry_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._reg_retry_task = None
        
    def _start_heartbeat(self) -> None:
        """Start a background task to refresh connector registration periodically."""
        if self._hb_task is None or self._hb_task.done():
            self._hb_task = asyncio.create_task(self._heartbeat_loop(), name="dsxconn-heartbeat")

    async def _cancel_heartbeat(self) -> None:
        task = self._hb_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._hb_task = None

    # ---- Auth helpers (dsx-connect API) ----
    def _apply_access_token(self, data: dict | None):
        try:
            if isinstance(data, dict) and data.get("access_token"):
                self._access_token = data.get("access_token")
                exp_in = int(data.get("expires_in") or 0)
                import time as _t
                self._access_expiry_ts = int(_t.time()) + max(0, exp_in - 5)
        except Exception:
            pass

    def _auth_headers(self) -> dict:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    async def _ensure_access_token(self):
        if not self._enrollment_token:
            return
        import time as _t
        now = int(_t.time())
        if self._access_token and self._access_expiry_ts and now < self._access_expiry_ts:
            return
        try:
            async with httpx.AsyncClient(verify=self._httpx_verify, timeout=10.0) as client:
                url = service_url(self.dsx_connect_url, API_PREFIX_V1, DSXConnectAPI.CONNECTORS_PREFIX, "token")
                r = await client.post(url, headers={"X-Enrollment-Token": self._enrollment_token})
                if r.status_code == 200:
                    self._apply_access_token(r.json())
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        """Periodically (re)register to refresh presence TTL in dsx-connect."""
        interval = max(5, int(getattr(self, "HEARTBEAT_INTERVAL_SECONDS", 60)))
        while True:
            try:
                await asyncio.sleep(interval)
                res = await self.register_connector(self.connector_running_model)
                if res.status == StatusResponseEnum.SUCCESS:
                    # keep quiet in steady state to avoid log spam
                    continue
                # On failures, log at warning with concise message
                dsx_logging.warning(f"Heartbeat register failed: {getattr(res, 'message', 'unknown')}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Non-fatal; try again next tick
                dsx_logging.debug(f"Heartbeat loop error: {e}", exc_info=True)

    async def _safe_repo_check_ok(self) -> bool:
        """
        Run repo check if provided; accept sync/async and multiple return shapes.

        Supported return types from connector @repo_check handler:
        - bool: True/False directly
        - StatusResponse: success => True, error => False
        - dict-like: interpreted if it contains a "status" field equal to "success"

        Defaults to True when no handler is registered.
        """
        if not self.repo_check_connection_handler:
            return True
        try:
            res = self.repo_check_connection_handler()
            if inspect.isawaitable(res):
                res = await res  # type: ignore[assignment]

            # Normalize common return types to a boolean
            try:
                from shared.models.status_responses import StatusResponse, StatusResponseEnum  # local import
            except Exception:  # pragma: no cover - defensive
                StatusResponse = None  # type: ignore
                StatusResponseEnum = None  # type: ignore

            # 1) Explicit bool
            if isinstance(res, bool):
                return res

            # 2) Pydantic StatusResponse
            if StatusResponse is not None and isinstance(res, StatusResponse):
                try:
                    return res.status == StatusResponseEnum.SUCCESS  # type: ignore[union-attr]
                except Exception:
                    return False

            # 3) dict-like with a status field
            if isinstance(res, dict):
                status = str(res.get("status", "")).lower()
                return status == "success"

            # 4) Fallback to truthiness (legacy); be conservative
            return bool(res)
        except Exception as e:
            dsx_logging.warning(f"repo_check raised error: {e}")
            return False

    # ----------------- outward calls -----------------

    async def scan_file_request(self, scan_request: ScanRequestModel) -> StatusResponse:
        if self.connector_running_model.status != ConnectorStatusEnum.READY:
            dsx_logging.warning(
                "Skipping scan request for %s because connector is not registered with dsx-connect (status=%s).",
                scan_request.location,
                self.connector_running_model.status.value,
            )
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                description="Connector not registered with dsx-connect",
                message="Scan request skipped because dsx-connect is unavailable.",
            )

        if self.connector_running_model.item_action_move_metainfo in scan_request.location:
            return StatusResponse(status=StatusResponseEnum.NOTHING, description="Quarantine path", message=f"Skip {scan_request.location}")
        scan_request.connector = self.connector_running_model
        scan_request.connector_url = self.connector_running_model.url
        # Ensure scan_job_id is set: use context from full_scan, else generate per-request id (e.g., webhook event)
        if not getattr(scan_request, "scan_job_id", None):
            job_ctx = _SCAN_JOB_ID.get()
            scan_request.scan_job_id = job_ctx or str(uuid.uuid4())
        # If in a full-scan job, increment the job enqueue counter
        try:
            if _SCAN_JOB_ID.get() == scan_request.scan_job_id:
                c = _SCAN_ENQ_COUNTER.get()
                _SCAN_ENQ_COUNTER.set(c + 1)
        except Exception:
            pass

        # Respect job pause: best-effort pre-check against dsx-connect job state
        try:
            job_id = getattr(scan_request, "scan_job_id", None)
            if job_id and _SCAN_JOB_ID.get() == job_id:
                # Only check when running within a full-scan context
                async with httpx.AsyncClient(verify=self._httpx_verify, timeout=5.0) as client:
                    raw_url = service_url(self.dsx_connect_url, API_PREFIX_V1, DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, f"{job_id}", "raw")
                    r = await client.get(raw_url)
                    if r.status_code == 200:
                        data = r.json().get("data", {})
                        if data.get("paused") == "1" or data.get("cancel") == "1":
                            dsx_logging.debug(f"Job {job_id} paused/cancelled; skipping enqueue for {scan_request.location}")
                            return StatusResponse(status=StatusResponseEnum.NOTHING,
                                                  message="Job paused",
                                                  description=f"scan_job_id={job_id}")
        except Exception:
            # Non-fatal: continue enqueue if state check fails
            pass
        try:
            async with httpx.AsyncClient(verify=self._httpx_verify) as client:
                url = service_url(self.dsx_connect_url, API_PREFIX_V1, DSXConnectAPI.SCAN_PREFIX, ScanPath.REQUEST)
                payload = jsonable_encoder(scan_request)
                import json as _json
                try:
                    content = _json.dumps(payload, separators=(",", ":")).encode()
                    hdrs = self._dsx_hmac_headers("POST", url, content)
                    resp = await client.post(url, content=content, headers=hdrs or None)
                except Exception:
                    hdrs = self._dsx_hmac_headers("POST", url, b"")
                    resp = await client.post(url, json=payload, headers=hdrs or None)
            resp.raise_for_status()
            self.scan_request_count += 1
            return StatusResponse(**resp.json())
        except httpx.ConnectError as e:
            dsx_logging.warning("dsx-connect unreachable during scan request: %s", e)
            return StatusResponse(
                status=StatusResponseEnum.ERROR,
                description="dsx-connect unreachable",
                message="Failed to deliver scan request; dsx-connect not reachable.",
            )
        except httpx.HTTPStatusError as e:
            dsx_logging.error("HTTP error during scan request", exc_info=True)
            return StatusResponse(status=StatusResponseEnum.ERROR, description="Failed to send scan request", message=str(e))
        except Exception as e:
            dsx_logging.error("Unexpected error during scan request", exc_info=True)
            return StatusResponse(status=StatusResponseEnum.ERROR, description="Unexpected error in scan request", message=str(e))

    async def get_status(self):
        dsxa_status = await self.test_dsx_connect()
        repo_ok = await self._safe_repo_check_ok()
        return {
            "connector_status": self.connector_running_model.status.value,
            "dsx-connect connectivity": "success" if dsxa_status else "failed",
            "repo connectivity": "success" if repo_ok else "failed",
            "scan_requests_since_active_count": self.scan_request_count,
        }

    async def register_connector(self, conn_model: ConnectorInstanceModel) -> StatusResponse:
        try:
            async with httpx.AsyncClient(verify=self._httpx_verify) as client:
                url = service_url(self.dsx_connect_url, API_PREFIX_V1, DSXConnectAPI.CONNECTORS_PREFIX, ConnectorPath.REGISTER_CONNECTORS)
                headers = {"X-Enrollment-Token": self._enrollment_token} if self._enrollment_token else None
                resp = await client.post(url, json=jsonable_encoder(conn_model), headers=headers)
                resp.raise_for_status()
                data = resp.json()
            self._apply_access_token(data if isinstance(data, dict) else None)
            try:
                if isinstance(data, dict):
                    kid = data.get("hmac_key_id")
                    sec = data.get("hmac_secret")
                    if kid and sec:
                        from connectors.framework.auth_hmac import set_runtime_hmac_credentials
                        set_runtime_hmac_credentials(kid, sec)
                        try:
                            setattr(self.connector_running_model, "hmac_key_id", kid)
                            setattr(self.connector_running_model, "hmac_secret", sec)
                        except Exception:
                            pass
            except Exception:
                pass
            return StatusResponse(**data)
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code == 401:
                msg = (
                    "Connector registration rejected (401 Unauthorized). "
                    "dsx-connect authentication is enabled; set DSXCONNECT_ENROLLMENT_TOKEN to the server's enrollment "
                    "token and restart this connector."
                )
                dsx_logging.error(msg)
            else:
                detail = e.response.text if e.response is not None else str(e)
                msg = f"HTTP {status_code} during connector registration: {detail}"
                dsx_logging.error(msg)
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Registration failed", description=msg)
        except httpx.RequestError as e:
            hint = "Verify dsx-connect URL, scheme and port, and that the service is reachable."
            dsx_logging.warning(f"Connector registration request error: {e}. {hint}")
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Registration failed", description=str(e))
        except Exception as e:
            dsx_logging.error("Unexpected error during connector registration", exc_info=True)
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Registration failed", description=str(e))

    async def _registration_retry_loop(self):
        """
        Retry registering with dsx-connect and verifying repo readiness until both are OK.
        Exponential backoff with jitter; keeps status at STARTING until success.
        """
        base_delay = 2.0
        max_delay = 60.0
        attempt = 0
        while True:
            attempt += 1
            try:
                reg = await self.register_connector(self.connector_running_model)
                repo_ok = await self._safe_repo_check_ok()
                if reg.status == StatusResponseEnum.SUCCESS and repo_ok:
                    # ensure heartbeat is running if the first attempt failed earlier
                    self._start_heartbeat()
                    self.connector_running_model.status = ConnectorStatusEnum.READY
                    dsx_logging.info(f"Connector READY after {attempt} attempt(s).")
                    return
                self.connector_running_model.status = ConnectorStatusEnum.STARTING
            except Exception as e:
                # register_connector already logs; keep loop robust
                dsx_logging.debug(f"Registration retry loop error: {e}")

            # Backoff with jitter
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = delay * 0.2 * (0.5 - random())
            sleep_for = max(1.0, delay + jitter)
            dsx_logging.info(f"Registration/repo retry in {sleep_for:.1f}s (attempt {attempt})")
            await asyncio.sleep(sleep_for)

    async def unregister_connector(self) -> StatusResponse:
        uuid_str = str(self.connector_running_model.uuid)
        url = service_url(self.dsx_connect_url,
                          API_PREFIX_V1,
                          DSXConnectAPI.CONNECTORS_PREFIX,
                          format_route(ConnectorPath.UNREGISTER_CONNECTORS, connector_uuid=uuid_str))
        try:
            async with httpx.AsyncClient(verify=self._httpx_verify) as client:
                hdrs = self._dsx_hmac_headers("DELETE", url, None)
                resp = await client.delete(url, headers=hdrs or None)
            if resp.status_code == 204:
                return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Unregistered",
                                      description=f"Removed {self.connector_running_model.url} : {self.connector_running_model.uuid}")
            resp.raise_for_status()
            return StatusResponse(**resp.json())
        except httpx.HTTPStatusError as e:
            msg = f"HTTP {e.response.status_code} during connector unregistration"
            dsx_logging.error(msg)
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Unregistration failed", description=msg)
        except httpx.RequestError as e:
            # Do not emit a traceback here; provide a concise hint instead
            hint = "Likely unreachable or timed out. Verify DSXCONNECTOR_DSX_CONNECT_URL, scheme/port, DNS, and service availability."
            dsx_logging.error(f"Unregister connector failed: {e}. {hint}")
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Unregistration failed", description=str(e))
        except Exception as e:
            # Unexpected error; still avoid traceback noise on shutdown
            dsx_logging.error(f"Unregister connector failed: {e}")
            return StatusResponse(status=StatusResponseEnum.ERROR, message="Unregistration failed", description=str(e))

    async def test_dsx_connect(self) -> Optional[dict]:
        try:
            async with httpx.AsyncClient(verify=self._httpx_verify) as client:
                url = service_url(self.dsx_connect_url, API_PREFIX_V1, DSXConnectAPI.CONNECTION_TEST)
                # no HMAC needed; public health
                resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            dsx_logging.warning(f"dsx-connect test failed: {e}")
            return None

class DSXAConnectorRouter(APIRouter):
    def __init__(self, connector: DSXConnector):
        super().__init__(prefix=f"/{connector.connector_running_model.name}")
        self._connector = connector

        self.get("/", description="Connector status and availability")(self.home)
        self.get(route_path(ConnectorAPI.HEALTHZ.value))(self.healthz)
        self.get(route_path(ConnectorAPI.READYZ.value))(self.readyz)

        self.put(route_path(ConnectorAPI.ITEM_ACTION.value),
                 description="Perform an action on an item",
                 response_model=ItemActionStatusResponse,
                 dependencies=[Depends(require_dsx_hmac)],
                 )(self.put_item_action)

        self.post(route_path(ConnectorAPI.FULL_SCAN.value),
                  description="Initiate a full scan",
                  response_model=StatusResponse,
                  dependencies=[Depends(require_dsx_hmac)],
                  )(self.post_full_scan)

        self.post(route_path(ConnectorAPI.READ_FILE.value),
                  description="Request a file from the connector",
                  response_model=None,
                  responses={
                      200: {"content": {"application/octet-stream": {}}},
                      404: {"content": {"application/json": {}}},
                      501: {"content": {"application/json": {}}},
                  },
                  dependencies=[Depends(require_dsx_hmac)],
                  )(self.post_read_file)

        self.get(route_path(ConnectorAPI.REPO_CHECK.value),
                 description="Check repository connectivity",
                 dependencies=[Depends(require_dsx_hmac)],
                 )(self.get_repo_check)

        # Optional estimation endpoint: returns count preflight if supported by connector.
        self.get(route_path(ConnectorAPI.ESTIMATE.value),
                 description="Estimate item count (exact or unknown)",
                 dependencies=[Depends(require_dsx_hmac)],
                 )(self.get_estimate)

        self.post(route_path(ConnectorAPI.WEBHOOK_EVENT.value),
                 description="Handle inbound webhook")(self.post_handle_webhook_event)

        self.get(route_path(ConnectorAPI.CONFIG.value),
                 description="Connector configuration",
                 dependencies=[Depends(require_dsx_hmac)],
                 )(self.get_config)
        # Register FastAPI events
        # self.on_event("startup")(self.on_startup_event)
        # self.on_event("shutdown")(self.on_shutdown_event)

    async def home(self):
        return await self._connector.get_status()

    async def healthz(self):
        return JSONResponse({"ok": True}, status_code=200)

    async def readyz(self):
        model = self._connector.connector_running_model
        is_ready = (model.status == ConnectorStatusEnum.READY)
        # Optionally redact fields that are noisy/sensitive on a public probe
        payload = jsonable_encoder(model.model_dump(
            # exclude={"asset", "filter"}  # uncomment if you don't want to expose these
        ))
        return JSONResponse(
            payload,
            status_code=200 if is_ready else 503,
        )

    async def put_item_action(self, scan_request_info: ScanRequestModel) -> ItemActionStatusResponse:
        if self._connector.item_action_handler:
            return await self._connector.item_action_handler(scan_request_info)
        return ItemActionStatusResponse(status=StatusResponseEnum.ERROR,
                                        item_action=ItemActionEnum.NOT_IMPLEMENTED,
                                        message="No handler registered for quarantine_action",
                                        description="Add a decorator (ex: @connector.item_action) to handle item_action requests")

    async def _run_full_scan(self, limit: int | None, job_id: str):
        """Run connector full_scan handler within a scan-job context."""
        token = _SCAN_JOB_ID.set(job_id)
        ctoken = _SCAN_ENQ_COUNTER.set(0)
        try:
            handler = self._connector.full_scan_handler
            if not handler:
                return
            # Call with limit if supported
            try:
                params = inspect.signature(handler).parameters
                if 'limit' in params:
                    await handler(limit)  # type: ignore[misc]
                else:
                    await handler()  # type: ignore[misc]
            except ValueError:
                # Fallback: call without inspection
                await handler()  # type: ignore[misc]
        except Exception as e:
            dsx_logging.error(f"full_scan background task error: {e}", exc_info=True)
        finally:
            try:
                _SCAN_JOB_ID.reset(token)
            except Exception:
                pass
            # Best-effort: report enqueue_done with enqueued_total to dsx-connect
            try:
                enq_total = int(_SCAN_ENQ_COUNTER.get())
            except Exception:
                enq_total = -1
            try:
                async with httpx.AsyncClient(verify=self._httpx_verify) as client:
                    url = service_url(self.dsx_connect_url, API_PREFIX_V1,
                                      DSXConnectAPI.SCAN_PREFIX, ScanPath.JOBS, job_id, 'enqueue_done')
                    payload: dict[str, Any] = {}
                    if enq_total >= 0:
                        payload = {"enqueued_total": enq_total}
                    try:
                        import json as _json
                        content = _json.dumps(payload, separators=(",", ":")).encode() if payload else None
                    except Exception:
                        content = None
                    hdrs = self._connector._dsx_hmac_headers("POST", url, content)
                    resp = await client.post(url, json=payload, headers=hdrs or None)
                    dsx_logging.info(f"enqueue_done posted job={job_id} enqueued_total={enq_total} status={resp.status_code}")
            except Exception:
                pass
            try:
                _SCAN_ENQ_COUNTER.reset(ctoken)
            except Exception:
                pass

    async def post_full_scan(self, request: Request, background_tasks: BackgroundTasks) -> StatusResponse:
        # Optional limit=N query to enqueue a small sample for testing
        limit_q = request.query_params.get("limit")
        try:
            limit = int(limit_q) if limit_q is not None else None
            if limit is not None and limit < 1:
                limit = 1
        except Exception:
            limit = None

        if self._connector.full_scan_handler:
            # Allow caller to provide job_id, else generate a new one
            job_id = request.query_params.get("job_id") or str(uuid.uuid4())
            # Schedule within the running event loop to avoid threadpool/no-loop issues
            asyncio.create_task(self._run_full_scan(limit, job_id))
            return StatusResponse(
                status=StatusResponseEnum.SUCCESS,
                message="Full scan initiated",
                description=(
                    "The scan is running in the background. "
                    f"job_id={job_id}{f' limit={limit}' if limit else ''}"
                )
            )
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message="No handler registered for full_scan",
                              description="Add a decorator (ex: @connector.full_scan) to handle full scan requests")



    async def post_read_file(self, scan_request_info: ScanRequestModel) -> Response:
        dsx_logging.debug(f"Receive read_file request for {scan_request_info}")

        if self._connector.read_file_handler:
            res = await self._connector.read_file_handler(scan_request_info)

            # If downstream gave us a Response (e.g., StreamingResponse), pass it through
            if isinstance(res, Response):
                return res

            # If downstream returned a Pydantic model or dict, JSON-encode it
            try:
                # StatusResponse is a Pydantic model; model_dump() in Pydantic v2
                payload = res.model_dump()  # type: ignore[attr-defined]
            except Exception:
                payload = jsonable_encoder(res)

            return JSONResponse(content=payload)

        # No handler registered: return JSON error
        return JSONResponse(
            content=StatusResponse(
                status=StatusResponseEnum.ERROR,
                message="No event handler registered for read_file",
                description="Add a decorator (e.g., @connector.read_file) to handle read_file requests",
            ).model_dump(),
            status_code=501,
        )

    async def get_repo_check(self, request: Request) -> StatusResponse:
        # Optional preview query (?preview=N) for a non-destructive sample listing
        try:
            limit_q = request.query_params.get("preview")
            preview_limit = max(0, int(limit_q)) if limit_q is not None else 0
        except Exception:
            preview_limit = 0

        # Base connectivity result
        dsx_logging.debug(f"repo_check called (preview={preview_limit})")
        if self._connector.repo_check_connection_handler:
            res = self._connector.repo_check_connection_handler()
            if inspect.isawaitable(res):
                res = await res  # type: ignore
            status = res if isinstance(res, StatusResponse) else StatusResponse(
                status=StatusResponseEnum.SUCCESS if bool(res) else StatusResponseEnum.ERROR,
                message="Repository connectivity success" if bool(res) else "Repository connectivity failed"
            )
        else:
            status = StatusResponse(status=StatusResponseEnum.ERROR,
                                    message="No event handler registered for repo_check",
                                    description="Add a decorator (ex: @connector.repo_check) to handle repo check requests")

        # Attach preview (no scanning side-effects)
        provider = self._connector.preview_provider
        if preview_limit and provider is not None:
            try:
                items = await provider(preview_limit)
                status.preview = items[:preview_limit]
                status.description = (status.description + ' | ' if status.description else '') + f"preview={len(status.preview)}"
            except Exception as e:
                dsx_logging.warning(f"preview provider failed: {e}")
        return status

    async def get_estimate(self, request: Request) -> dict:
        """
        Default count estimate: unknown. Connectors can override by providing a provider
        on the connector instance (estimate_provider) that returns
        {"count": int | None, "confidence": "exact" | "unknown"}.
        """
        try:
            provider = getattr(self._connector, "estimate_provider", None)
            if provider is not None:
                out = await provider()
                if isinstance(out, dict) and "confidence" in out and "count" in out:
                    return out
        except Exception:
            pass
        return {"count": None, "confidence": "unknown"}

    async def post_handle_webhook_event(self, request: Request):
        if self._connector.webhook_handler:
            # Handle Graph-like validation handshake (validationToken query parameter)
            validation_token = request.query_params.get("validationToken")
            if validation_token:
                # Microsoft Graph requires the raw token echoed as the response body with 200 OK
                dsx_logging.debug("Validation token received; echoing for webhook handshake.")
                return Response(content=str(validation_token), media_type="text/plain", status_code=200)
            # Parse the JSON payload from the request body
            event = await request.json()
            dsx_logging.info(f"Received webhook for artifact path: {event}")
            return await self._connector.webhook_handler(event)
        # dpx_logging.info(f"Received webhook for file: {event.name} at {event.repo_key}/{event.path}")
        # Trigger a scan or other processing as required
        # await connector.scan_file_request(ScanEventQueueModel(location=event.path, metainfo=event.name))
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message="No handler registered for webhook_event",
                              description="Add a decorator (ex: @connector.webhook_event) to handle webhook events")

    async def get_config(self):
        if self._connector.config_handler:
            return await self._connector.config_handler(self._connector.connector_running_model)
        return self._connector.connector_running_model
