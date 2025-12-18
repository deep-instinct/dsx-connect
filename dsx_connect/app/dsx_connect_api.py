import asyncio
import json
import os
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from http.client import HTTPException

from redis.asyncio import Redis
from fastapi import FastAPI, Request, Path, APIRouter, Depends, Query
from fastapi.staticfiles import StaticFiles

import uvicorn
import pathlib

from starlette import status
from starlette.responses import FileResponse, StreamingResponse, JSONResponse

from dsx_connect.config import get_config, get_auth_config
from dsx_connect.connectors.registry import ConnectorsRegistry
from dsx_connect.messaging.bus import Bus
from dsx_connect.messaging.channels import Channel
from dsx_connect.messaging.notifiers import Notifiers


from shared.routes import (
    API_PREFIX_V1,
    DSXConnectAPI,
    NotificationPath,
    route_name,
    Action, route_path,
)
from dsx_connect.dsxa_client.dsxa_client import DSXAClient
from shared.dsx_logging import dsx_logging

from dsx_connect.app.dependencies import static_path
from dsx_connect.app.routers import scan_request, scan_results, connectors, dead_letter, dianna
from dsx_connect import version

# ---- Helper functions ----

def get_redis(request: Request) -> Redis | None:
    """Return the shared async Redis client stashed on app.state (or None)."""
    return getattr(request.app.state, "redis", None)

def get_registry(request: Request) -> ConnectorsRegistry | None:
    """Return the shared async Redis client stashed on app.state (or None)."""
    return getattr(request.app.state, "registry", None)


async def _start_services(app: FastAPI, cfg):
    # 1) Create the single AsyncRedis client for the whole app
    try:
        app.state.redis = Redis.from_url(
            str(cfg.redis_url),
            decode_responses=True,
            socket_connect_timeout=0.5,   # fast-fail
            socket_keepalive=False,
        )
        await app.state.redis.ping()
        dsx_logging.info("Redis connection established.")
    except Exception as e:
        app.state.redis = None
        # concise one-line error; no traceback
        dsx_logging.error(f"Redis unavailable at startup: {e.__class__.__name__}: {e}")

    # 2) Start the connector registry using the redis client
    try:
        if app.state.redis is not None:
            app.state.registry = ConnectorsRegistry(app.state.redis, sweep_period=20)
            await app.state.registry.start()
            dsx_logging.info("Connector registry started.")
        else:
            app.state.registry = None
            dsx_logging.warning("Connector registry disabled (no Redis).")
    except Exception as e:
        app.state.registry = None
        dsx_logging.error(f"Connector registry startup failed: {e.__class__.__name__}: {e}")

    # 3) Start the messaging notification bus with the redis instance
    try:
        if app.state.redis is not None:
            bus = Bus(app.state.redis)
            app.state.bus = bus
            app.state.notifiers = Notifiers(bus)
            dsx_logging.info("Messaging notifier bus started.")
        else:
            app.state.notifier = None
            dsx_logging.warning("Messaging notifier bus disabled (no Redis).")
    except Exception as e:
        app.state.notifier = None
        dsx_logging.error(f"Messaging notifier bus startup failed: {e.__class__.__name__}: {e}")

async def _stop_services(app):
    if getattr(app.state, "registry", None):
        await app.state.registry.stop()
    if getattr(app.state, "redis", None):
        await app.state.redis.aclose()
    # cancel reconnect loop if running
    task = getattr(app.state, "redis_reconnect_task", None)
    if task:
        task.cancel()


async def _redis_reconnect_loop(app: FastAPI, cfg):
    """Background loop: try to (re)establish Redis, registry, and notifiers when unavailable.

    Logs an info once when connections come up after being down. Uses capped exponential backoff.
    """
    backoff = 1.0
    while True:
        try:
            # If we have a client, ensure it's healthy; on failure, drop it and restart services
            if getattr(app.state, "redis", None) is not None:
                try:
                    await app.state.redis.ping()
                except Exception as e:
                    dsx_logging.warning(f"Redis ping failed, will attempt reconnect: {e.__class__.__name__}: {e}")
                    # tear down
                    try:
                        if getattr(app.state, "registry", None):
                            await app.state.registry.stop()
                    except Exception:
                        pass
                    try:
                        if getattr(app.state, "redis", None):
                            await app.state.redis.aclose()
                    except Exception:
                        pass
                    app.state.redis = None
                    app.state.registry = None
                    app.state.notifiers = None

            # If no Redis, try to create one and start dependent services
            if getattr(app.state, "redis", None) is None:
                try:
                    client = Redis.from_url(
                        str(cfg.redis_url), decode_responses=True, socket_connect_timeout=0.5, socket_keepalive=False
                    )
                    await client.ping()
                    app.state.redis = client
                    dsx_logging.info("Redis connection re-established.")
                    # start registry
                    try:
                        app.state.registry = ConnectorsRegistry(app.state.redis, sweep_period=20)
                        await app.state.registry.start()
                        dsx_logging.info("Connector registry started (after reconnect).")
                    except Exception as e:
                        app.state.registry = None
                        dsx_logging.error(f"Connector registry start failed after reconnect: {e}")
                    # start notifier bus
                    try:
                        bus = Bus(app.state.redis)
                        app.state.bus = bus
                        app.state.notifiers = Notifiers(bus)
                        dsx_logging.info("Messaging notifier bus started (after reconnect).")
                    except Exception as e:
                        app.state.notifiers = None
                        dsx_logging.error(f"Notifier bus start failed after reconnect: {e}")
                    backoff = 1.0  # reset backoff after success
                except Exception:
                    # keep None and backoff
                    pass

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            # don't crash the loop; log and keep trying
            dsx_logging.warning(f"Redis reconnect loop error: {e}")
            await asyncio.sleep(5.0)

# ---- FastAPI app Startup ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()  # envs are already present in Docker
    app.state.config = config  # stash if routes need it

    dsx_logging.info(f"dsx-connect version: {version.DSX_CONNECT_VERSION}")
    dsx_logging.info(f"dsx-connect configuration: {config}")
    try:
        auth_cfg = get_auth_config()
        if getattr(auth_cfg, "enabled", False):
            dsx_logging.info("Connector authentication enabled (enrollment token + DSX-HMAC).")
    except Exception:
        dsx_logging.warning("Failed to load auth configuration; skipping auth status log.")
    dsx_logging.info("dsx-connect startup completed.")

    await _start_services(app, config)
    # start reconnect loop in background
    app.state.redis_reconnect_task = asyncio.create_task(_redis_reconnect_loop(app, config))
    try:
        yield
    finally:
        await _stop_services(app)


    dsx_logging.info("dsx-connect shutdown completed.")


app = FastAPI(title='dsx-connect API',
              description='Deep Instinct Data Security X Connect for Applications API',
              version=version.DSX_CONNECT_VERSION,
              docs_url='/docs',
              lifespan=lifespan)

app.mount("/static", StaticFiles(directory=static_path, html=True), name='static')

# Add CSP for the main HTML page even when accessed via the static path
@app.middleware("http")
async def add_csp_header(request: Request, call_next):
    response = await call_next(request)
    # Apply CSP only to our HTML entrypoints
    if request.url.path in ("/", "/static/html/dsx_connect.html"):
        response.headers["Content-Security-Policy"] = "img-src 'self' data:; object-src 'none'"
    return response

api = APIRouter(prefix=route_path(API_PREFIX_V1), tags=["core"])


@api.get(route_path(DSXConnectAPI.CONFIG.value),
         name=route_name(DSXConnectAPI.CONFIG, action=Action.GET),
         description="Get all configuration",
         status_code=status.HTTP_200_OK)
def get_config_all():
    return get_config()


@api.get(route_path("meta"),
         name=route_name(DSXConnectAPI.CONFIG, action=Action.LIST) + ":meta",
         description="Version and build metadata",
         status_code=status.HTTP_200_OK)
def get_meta():
    build_ts = os.getenv("DSX_BUILD_TIMESTAMP") or datetime.now(timezone.utc).isoformat()
    return {
        "version": getattr(version, "DSX_CONNECT_VERSION", "unknown"),
        "build_timestamp": build_ts,
    }


@api.get(route_path(DSXConnectAPI.VERSION.value),
         name=route_name(DSXConnectAPI.VERSION, action=Action.GET),
         description="Get version",
         status_code=status.HTTP_200_OK)
def get_version():
    return version.DSX_CONNECT_VERSION

@api.get(route_path(DSXConnectAPI.DSXA_CONNECTION_TEST.value),
         name=route_name(DSXConnectAPI.DSXA_CONNECTION_TEST, action=Action.DSXA_CONNECTION),
         description="Test connection to dsxa scanner.",
         status_code=status.HTTP_200_OK)
async def get_dsxa_test_connection():
    dsxa_client = DSXAClient(get_config().scanner.scan_binary_url)
    return await dsxa_client.test_connection_async()


@api.get(
    route_path(DSXConnectAPI.HEALTHZ.value),
    name=route_name(DSXConnectAPI.HEALTHZ, action=Action.HEALTH),
    description="Liveness probe: process is up."
)
async def healthz():
    return {"status": "alive"}

@api.get(
    route_path(DSXConnectAPI.READYZ.value),
    name=route_name(DSXConnectAPI.READYZ, action=Action.READY),
    description="Readiness probe: dependencies available (e.g., Redis)."
)
async def readyz(redis = Depends(get_redis), registry = Depends(get_registry), app = Depends(lambda: app)):
    ready = True
    details = {}

    # Redis
    try:
        if redis is None:
            ready = False
            details["redis"] = "unavailable"
        else:
            await redis.ping()
            details["redis"] = "ok"
    except Exception as e:
        ready = False
        details["redis"] = f"error: {e}"

    # Registry (optional, depends on Redis)
    if registry is None:
        details["registry"] = "unavailable"
        # don't flip ready to False here if you consider registry optional;
        # set ready=False if it's mandatory:
        # ready = False
    else:
        details["registry"] = "ok"

    status_code = 200 if ready else 503
    payload = {"status": "ready" if ready else "not_ready", **details}
    return JSONResponse(payload, status_code=status_code)



# ---- Server-Sent Events (SSE) ----
sse_notifications = APIRouter(prefix=route_path(API_PREFIX_V1), tags=["server side event stream"])


@sse_notifications.get(
    route_path(DSXConnectAPI.NOTIFICATIONS_PREFIX, NotificationPath.SCAN_RESULT),
    name=route_name(DSXConnectAPI.NOTIFICATIONS_PREFIX, NotificationPath.SCAN_RESULT, Action.LIST),
    description="SSE stream of scan result notifications",
)
async def notifications_scan_result(request: Request):
    LOG_SSE = os.getenv('DSX_LOG_SSE_EVENTS', '0') == '1'
    async def stream():
        # Initial connected and retry hints
        yield 'data: {"type":"connected"}\n\n'
        yield 'retry: 5000\n'
        hb = 0

        while True:
            # Wait for notifier availability
            if not hasattr(request.app.state, 'notifiers') or request.app.state.notifiers is None:
                yield 'data: {"type":"waiting","message":"Notifier unavailable"}\n\n'
                for _ in range(5):
                    if await request.is_disconnected():
                        return
                    yield 'data: {"type":"heartbeat"}\n\n'
                    await asyncio.sleep(1.0)
                continue

            try:
                async for raw in request.app.state.notifiers.subscribe_scan_results():
                    if await request.is_disconnected():
                        return
                    # Normalize to JSON string for SSE data
                    try:
                        from json import dumps
                        if isinstance(raw, (bytes, bytearray)):
                            data = raw.decode()
                        elif isinstance(raw, str):
                            data = raw
                        else:
                            data = dumps(raw, separators=(",", ":"))
                    except Exception:
                        data = str(raw)
                    if LOG_SSE:
                        try:
                            dsx_logging.info(f"sse.scan_result len={len(data)} data={data[:256]}")
                        except Exception:
                            pass
                    yield f"data: {data}\n\n"
                    hb += 1
                    if hb >= 10:
                        yield 'data: {"type":"heartbeat"}\n\n'
                        hb = 0
                    await asyncio.sleep(0)
            except Exception as e:
                dsx_logging.warning(f"SSE scan result stream disconnected: {e.__class__.__name__}: {e}")
                # Fall back to heartbeat loop, then retry
                for _ in range(5):
                    if await request.is_disconnected():
                        return
                    yield 'data: {"type":"heartbeat"}\n\n'
                    await asyncio.sleep(1.0)
                continue

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@sse_notifications.get(
    route_path(DSXConnectAPI.NOTIFICATIONS_PREFIX, NotificationPath.JOB_SUMMARY, "{job_id}"),
    name=route_name(DSXConnectAPI.NOTIFICATIONS_PREFIX, NotificationPath.JOB_SUMMARY, Action.LIST),
    description="SSE stream emitting periodic job summaries (heartbeat-style)",
)
async def notifications_job_summary(
    job_id: str = Path(..., description="Scan job identifier"),
    request: Request = None,
    interval: float = Query(5.0, ge=2.0, le=60.0, description="Summary interval in seconds (2-60)"),
):
    async def stream():
        import time as _t
        from json import dumps as _dumps
        # Initial retry hint and connected frame
        yield "retry: 5000\n"
        yield f'data: {{"type":"connected","job_id":"{job_id}"}}\n\n'

        period = float(interval) if interval and interval > 0 else 5.0
        while True:
            try:
                if await request.is_disconnected():
                    return
                r = getattr(request.app.state, "redis", None)
                if r is None:
                    yield 'data: {"type":"heartbeat","status":"redis_unavailable"}\n\n'
                    await asyncio.sleep(period)
                    continue
                key = f"dsxconnect:job:{job_id}"
                data = await r.hgetall(key)
                if not data:
                    # Send sentinel once and slow down
                    yield f'data: {{"type":"job_summary","job_id":"{job_id}","status":"not_found"}}\n\n'
                    await asyncio.sleep(period)
                    continue
                # Derive duration and ETA similar to GET /scan/jobs/{job_id}
                try:
                    # Normalize ints
                    def _toi(v, default=0):
                        try:
                            return int(v)
                        except Exception:
                            return default
                    enq = _toi(data.get("enqueued_count"), 0)
                    proc = _toi(data.get("processed_count"), 0)
                    exp = _toi(data.get("expected_total"), -1)
                    enq_total = _toi(data.get("enqueued_total"), -1)
                    total = enq_total if enq_total >= 0 else (exp if exp >= 0 else None)
                    started = _toi(data.get("started_at"), 0)
                    finished = _toi(data.get("finished_at"), 0)
                    now = int(_t.time())
                    duration = ((finished or now) - started) if started else None
                    eta = None
                    if total and total > 0 and started and proc > 0 and (not finished) and proc < total:
                        elapsed = max(1, (finished or now) - started)
                        throughput = proc / elapsed
                        if throughput > 0:
                            remaining = max(0, total - proc)
                            eta = int(remaining / throughput)
                    # Friendly remaining time
                    def _fmt_eta(sec: int | None) -> str | None:
                        if sec is None or sec < 0:
                            return None
                        d, rem = divmod(sec, 86400)
                        h, rem = divmod(rem, 3600)
                        m, s = divmod(rem, 60)
                        return f"{d}d {h:02d}:{m:02d}:{s:02d}" if d > 0 else f"{h:02d}:{m:02d}:{s:02d}"

                    payload = {
                        "type": "job_summary",
                        "ts": now,
                        "job": {
                            "job_id": job_id,
                            "status": data.get("status", "running"),
                            "processed_count": proc,
                            "total": total,
                            "duration_secs": duration,
                            "eta_secs": eta,
                            "time_remaining": _fmt_eta(eta),
                            "last_update": data.get("last_update"),
                        },
                    }
                    yield f"data: {_dumps(payload, separators=(',', ':'))}\n\n"
                except Exception:
                    yield 'data: {"type":"heartbeat","status":"error"}\n\n'
                await asyncio.sleep(period)
            except asyncio.CancelledError:
                return
            except Exception:
                # Back off slightly on unexpected errors
                await asyncio.sleep(period)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@sse_notifications.get(route_path(DSXConnectAPI.NOTIFICATIONS_PREFIX.value,
                                  NotificationPath.CONNECTOR_REGISTERED.value),
                       name=route_name(DSXConnectAPI.NOTIFICATIONS_PREFIX, NotificationPath.CONNECTOR_REGISTERED, Action.LIST),
                       description="SSE stream of connector registration events"
                       )
async def connector_registered_stream(request: Request):
    async def stream():
        from contextlib import suppress
        try:
            yield "retry: 5000\n"
            yield 'data: {"type":"connected","message":"Connector SSE stream started"}\n\n'

            # Check if notifier is available before attempting to listen
            if not hasattr(request.app.state, 'notifiers') or request.app.state.notifiers is None:
                # Keep the connection open; heartbeat until notifier becomes available
                yield 'data: {"type":"waiting","message":"Notifier unavailable"}\n\n'
                while (not hasattr(request.app.state, 'notifiers') or request.app.state.notifiers is None):
                    if await request.is_disconnected():
                        return
                    yield 'data: {"type":"heartbeat"}\n\n'
                    await asyncio.sleep(5.0)

            q: asyncio.Queue[bytes | str] = asyncio.Queue()

            async def reader():
                try:
                    async for raw in request.app.state.notifiers.subscribe_connector_notify():
                        await q.put(raw)
                except Exception as e:
                    # Signal error to main loop
                    await q.put(f'{{"type":"error","message":"Reader error: {str(e)}"}}')

            reader_task = asyncio.create_task(reader())
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        raw = await asyncio.wait_for(q.get(), timeout=10.0)
                        if isinstance(raw, str) and raw.startswith('{"type":"error"'):
                            yield f"data: {raw}\n\n"
                            break
                        # Normalize to JSON string for SSE
                        from json import dumps
                        if isinstance(raw, (bytes, bytearray)):
                            data = raw.decode("utf-8", "replace")
                        elif isinstance(raw, str):
                            data = raw
                        else:
                            data = dumps(raw, separators=(",", ":"))
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield 'data: {"type":"heartbeat"}\n\n'
                    await asyncio.sleep(0)
            finally:
                reader_task.cancel()
                with suppress(Exception):
                    await reader_task
        except Exception as e:
            dsx_logging.warning(f"SSE connector stream disconnected: {e.__class__.__name__}: {e}")
            yield 'data: {"type":"heartbeat"}\n\n'

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

app.include_router(api)

app.include_router(sse_notifications)
app.include_router(scan_request.router, tags=["scan"])
app.include_router(scan_results.router, tags=["results"])
app.include_router(connectors.router, tags=["connectors"])
app.include_router(dianna.router, tags=["dianna"])
app.include_router(dead_letter.router, tags=["dead-letter"])


@app.get("/")
def home(request: Request):
    home_path = pathlib.Path(static_path / 'html/dsx_connect.html')
    # Add a narrow CSP to block external image fetches (including from inside SVGs)
    csp = "img-src 'self' data:; object-src 'none'"
    return FileResponse(home_path, headers={
        "Content-Security-Policy": csp
    })


# Main entry point to start the FastAPI app
if __name__ == "__main__":
    # Uvicorn will serve the FastAPI app and keep it running
    uvicorn.run("dsx_connect_api:app", host="0.0.0.0", port=8586, reload=True, workers=1)
