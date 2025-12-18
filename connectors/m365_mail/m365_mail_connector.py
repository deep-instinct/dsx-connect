import asyncio
import json
from urllib.parse import quote

import httpx
from fastapi.encoders import jsonable_encoder
from starlette.responses import StreamingResponse
from shared.dsx_logging import dsx_logging
# Import module as alias so connector_api updates propagate
from connectors.framework import dsx_connector as dsx_framework
from connectors.framework.dsx_connector import DSXConnector
from connectors.m365_mail.config import config
from connectors.m365_mail.graph_client import GraphClient
from connectors.m365_mail.subscriptions import SubscriptionManager
from fastapi import Request, Response
from connectors.framework.auth_hmac import build_outbound_auth_header
from shared.models.connector_models import ConnectorInstanceModel, ConnectorStatusEnum, ScanRequestModel, ItemActionEnum
from shared.models.status_responses import StatusResponse, StatusResponseEnum
from shared.routes import service_url, API_PREFIX_V1, DSXConnectAPI


connector = DSXConnector(config)
connector_api = dsx_framework.connector_api
_graph: GraphClient | None = None
_subs_mgr: SubscriptionManager | None = None
_subs_task = None
_delta_task = None
_delta_lock: asyncio.Lock | None = None
_STATE_NS = "m365"


def _actions_enabled() -> bool:
    """Determine whether remediation actions should run."""
    desired = getattr(config, "item_action", ItemActionEnum.NOTHING)
    wants_action = desired not in (ItemActionEnum.NOTHING, ItemActionEnum.NOT_IMPLEMENTED)
    legacy_toggle = getattr(config, "enable_actions", None)
    if legacy_toggle is None:
        return wants_action
    return bool(legacy_toggle) and wants_action


def _configured_upns() -> list[str]:
    raw = getattr(config, "mailbox_upns", None)
    if not raw:
        return []
    normalized = str(raw).replace("\n", ",")
    return [u.strip() for u in normalized.split(",") if u.strip()]


def _delta_state_key(upn: str) -> str:
    return f"delta:{upn}"


def _state_url(key: str) -> str | None:
    try:
        uuid_str = str(connector.connector_running_model.uuid)
    except Exception:
        return None
    encoded_key = quote(key, safe="")
    base = str(config.dsx_connect_url)
    return service_url(base, API_PREFIX_V1, DSXConnectAPI.CONNECTORS_PREFIX,
                       "state", uuid_str, _STATE_NS, encoded_key)


def _signed_headers(method: str, url: str, body: bytes | None = None) -> dict[str, str]:
    header = build_outbound_auth_header(method, url, body)
    return {"Authorization": header} if header else {}


async def _kv_get(key: str) -> str | None:
    url = _state_url(key)
    if not url:
        return None
    headers = _signed_headers("GET", url, None)
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as client:
            resp = await client.get(url, headers=headers or None)
        resp.raise_for_status()
        data = resp.json()
        value = data.get("value")
        return value or None
    except Exception as e:
        dsx_logging.debug(f"state_get_failed key={key}: {e}")
        return None


async def _kv_put(key: str, value: str) -> None:
    url = _state_url(key)
    if not url:
        return
    body = value.encode()
    headers = {"Content-Type": "text/plain"}
    headers.update(_signed_headers("PUT", url, body))
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=config.verify_tls) as client:
            resp = await client.put(url, content=body, headers=headers)
        resp.raise_for_status()
    except Exception as e:
        dsx_logging.debug(f"state_put_failed key={key}: {e}")


def _ensure_delta_lock() -> asyncio.Lock:
    global _delta_lock
    if _delta_lock is None:
        _delta_lock = asyncio.Lock()
    return _delta_lock


async def _run_delta_for_mailbox(upn: str, limit: int | None) -> dict:
    if _graph is None:
        raise RuntimeError("graph_not_configured")
    token_key = _delta_state_key(upn)
    cursor = await _kv_get(token_key)
    next_cursor = cursor or None
    enqueued = 0
    pages = 0
    completed = True

    while True:
        remaining = None if limit is None else max(limit - enqueued, 0)
        if remaining is not None and remaining == 0:
            completed = False
            break
        msgs, next_link, delta_link = await _graph.delta_messages(upn, next_cursor)
        pages += 1
        if not msgs and not next_link and not delta_link:
            break
        for msg in msgs:
            if not msg.get("hasAttachments"):
                continue
            mid = msg.get("id")
            if not mid:
                continue
            try:
                attachments = await _graph.list_attachments(upn, mid)
            except Exception as e:
                dsx_logging.warning(f"list_attachments failed user={upn} mid={mid}: {e}")
                continue
            for att in attachments:
                if not str(att.get("@odata.type", "")).lower().endswith("fileattachment"):
                    continue
                att_id = att.get("id")
                if not att_id:
                    continue
                name = att.get("name") or att.get("contentType") or "attachment"
                uri = f"m365://{upn}/messages/{mid}/attachments/{att_id}"
                req = ScanRequestModel(location=uri, metainfo=str(name))
                await connector.scan_file_request(req)
                enqueued += 1
                if limit is not None and enqueued >= limit:
                    completed = False
                    break
            if limit is not None and enqueued >= limit:
                break
        if limit is not None and enqueued >= limit:
            break
        if next_link:
            next_cursor = next_link
            continue
        if delta_link:
            if completed:
                await _kv_put(token_key, delta_link)
            break
        break

    return {"enqueued": enqueued, "completed": completed, "pages": pages}


async def _delta_runner(limit: int | None = None) -> dict:
    if _graph is None:
        return {"status": "error", "message": "graph_not_configured"}
    upns = _configured_upns()
    if not upns:
        return {"status": "error", "message": "no_mailboxes_configured"}
    lock = _ensure_delta_lock()
    had_error = False
    details: list[dict] = []
    total = 0
    async with lock:
        for upn in upns:
            remaining = None if limit is None else max(limit - total, 0)
            if remaining is not None and remaining == 0:
                break
            try:
                result = await _run_delta_for_mailbox(upn, remaining)
                total += result.get("enqueued", 0)
                details.append({"upn": upn, **result})
            except Exception as e:
                had_error = True
                dsx_logging.warning(f"Delta runner failed for {upn}: {e}")
                details.append({"upn": upn, "error": str(e)})
        status = "success" if not had_error else "partial"
        return {"status": status, "enqueued": total, "details": details}


def _kick_delta_for_upns(upns: list[str]) -> None:
    if not upns:
        return
    try:
        from fastapi import BackgroundTasks
    except ImportError:
        BackgroundTasks = None

    async def _run_once(targets: list[str]):
        lock = _ensure_delta_lock()
        async with lock:
            results = []
            for upn in targets:
                try:
                    res = await _run_delta_for_mailbox(upn, None)
                    results.append({"upn": upn, **res})
                except Exception as exc:
                    dsx_logging.warning(f"delta_kick_failed upn={upn}: {exc}")
            if results:
                total = sum(r.get("enqueued", 0) for r in results)
                dsx_logging.info(f"delta.kick enqueued={total} details={results}")

    targets = sorted(set(upns))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        loop.create_task(_run_once(targets))
    else:
        asyncio.run(_run_once(targets))


@connector.startup
async def startup_event(base: ConnectorInstanceModel) -> ConnectorInstanceModel:
    dsx_logging.info(f"{base.name} startup. tenant={config.tenant_id} client_id={config.client_id}")
    # Initialize Graph client
    global _graph
    try:
        if config.tenant_id and config.client_id and config.client_secret:
            _graph = GraphClient(config.tenant_id, config.client_id, config.client_secret, config.authority)
        else:
            _graph = None
    except Exception as e:
        _graph = None
        dsx_logging.error(f"Graph client init failed: {e}")
    base.status = ConnectorStatusEnum.STARTING
    base.meta_info = "M365 Mail connector initialising"
    # Kick off subscription reconciliation in background if upns configured
    try:
        upns = _configured_upns()
        if _graph and upns:
            global _subs_mgr, _subs_task
            _subs_mgr = SubscriptionManager(_graph.token)
            if getattr(config, "webhook_base_url", None):
                connector_base = str(config.webhook_base_url).rstrip("/")
            else:
                connector_base = str(config.connector_url).rstrip("/")
            webhook_url = f"{connector_base}/{config.name}/webhook/event"
            async def _reconcile_loop():
                while True:
                    try:
                        summary = await _subs_mgr.reconcile_for_upns(upns, webhook_url)
                        dsx_logging.info(f"Subscriptions reconciled: {summary}")
                    except httpx.HTTPStatusError as e:
                        status = e.response.status_code if e.response is not None else "unknown"
                        msg = ""
                        try:
                            payload = e.response.json()
                            msg = payload.get("error", {}).get("message") or ""
                        except Exception:
                            msg = (e.response.text[:256] if e.response is not None else "")
                        hint = ""
                        if status == 400 and str(config.connector_url).startswith("http://"):
                            hint = " (Graph requires a publicly reachable HTTPS webhook URL—check DSXCONNECTOR_CONNECTOR_URL)"
                        dsx_logging.warning(
                            f"Subscription reconcile failed (HTTP {status}): {msg or e}. "
                            f"webhook_url={webhook_url}{hint}"
                        )
                    except Exception as e:
                        dsx_logging.warning(f"Subscription reconcile failed: {e}")
                    await asyncio.sleep(1800)  # 30 minutes
            _subs_task = asyncio.create_task(_reconcile_loop())
            # Start delta runner
            global _delta_task
            async def _delta_loop():
                while True:
                    try:
                        summary = await _delta_runner()
                        dsx_logging.info(f"Delta runner status={summary.get('status')} enqueued={summary.get('enqueued')}")
                    except Exception as e:
                        dsx_logging.warning(f"Delta loop error: {e}")
                    await asyncio.sleep(max(60, int(getattr(config, 'delta_run_interval_seconds', 600))))
            _delta_task = asyncio.create_task(_delta_loop())
        elif not upns:
            dsx_logging.info("No mailbox_upns configured; subscriptions and delta runner are disabled.")
    except Exception as e:
        dsx_logging.warning(f"Failed to start subscriptions loop: {e}")
    return base


@connector.repo_check
async def repo_check_handler() -> StatusResponse:
    # Minimal check: ensure we have basic config present
    missing = []
    if not config.tenant_id:
        missing.append("tenant_id")
    if not config.client_id:
        missing.append("client_id")
    if not (config.client_secret):
        missing.append("client_secret")
    if missing:
        return StatusResponse(status=StatusResponseEnum.ERROR,
                              message="Missing Graph configuration",
                              description=", ".join(missing))
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message="Graph config present")


@connector.webhook_event
async def webhook_handler(event: dict | ScanRequestModel) -> StatusResponse:
    try:
        # Handle Graph validation handshake (validationToken in querystring handled at ingress) or process notifications
        payload = event if isinstance(event, dict) else jsonable_encoder(event)
        dsx_logging.debug(f"Webhook payload: {json.dumps(payload)[:512]}...")
        if _graph is None:
            return StatusResponse(status=StatusResponseEnum.ERROR, message="graph_not_configured")
        # Graph notifications: {"value": [{"resource": "/users/{uid}/messages/{mid}", ...}, ...]}
        values = payload.get("value", []) if isinstance(payload, dict) else []
        # Verify clientState if configured
        try:
            if getattr(config, 'client_state', None):
                values = [v for v in values if v.get('clientState') == config.client_state]
        except Exception:
            pass
        if getattr(config, "trigger_delta_on_notification", False) and values:
            upns = []
            for v in values:
                try:
                    resource = v.get("resource", "")
                    parts = resource.strip("/").split("/")
                    if len(parts) >= 2 and parts[0].lower() == "users":
                        upns.append(parts[1])
                except Exception:
                    continue
            if upns:
                _kick_delta_for_upns(upns)
        enq = 0
        for v in values:
            resource = v.get("resource") or ""
            try:
                # parse /users/{uid}/messages/{mid}
                parts = resource.strip("/").split("/")
                if len(parts) >= 4 and parts[0] == 'users' and parts[2] == 'messages':
                    user = parts[1]
                    mid = parts[3]
                    msg = await _graph.fetch_message_min(user, mid)
                    if not msg.get("hasAttachments"):
                        continue
                    atts = await _graph.list_attachments(user, mid)
                    for a in atts:
                        if str(a.get("@odata.type", "")).lower().endswith("fileattachment"):
                            att_id = a.get("id")
                            name = a.get("name") or a.get("contentType") or "attachment"
                            uri = f"m365://{user}/messages/{mid}/attachments/{att_id}"
                            req = ScanRequestModel(location=uri, metainfo=str(name))
                            await connector.scan_file_request(req)
                            enq += 1
            except Exception as e:
                dsx_logging.warning(f"Notification processing error: {e}")
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="webhook_processed", description=f"enqueued={enq}")
    except Exception as e:
        dsx_logging.error(f"Webhook error: {e}", exc_info=True)
        return StatusResponse(status=StatusResponseEnum.ERROR, message="webhook_error", description=str(e))


def _parse_m365_uri(uri: str) -> tuple[str, str, str] | None:
    # m365://<user>/messages/<message_id>/attachments/<attachment_id>
    try:
        if not uri.startswith("m365://"):
            return None
        path = uri[len("m365://"):]
        parts = path.split("/")
        # Expect: [user, 'messages', message_id, 'attachments', attachment_id]
        if len(parts) >= 5 and parts[1] == 'messages' and parts[3] == 'attachments':
            return parts[0], parts[2], parts[4]
    except Exception:
        return None
    return None


@connector.read_file
async def read_file_handler(scan_request_info: ScanRequestModel):
    # Stream attachment content from Graph based on location URI
    uri = scan_request_info.location
    parsed = _parse_m365_uri(uri)
    if not parsed:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="unsupported_location", description=str(uri))
    user, message_id, att_id = parsed
    if _graph is None:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="graph_not_configured")
    async def iter_stream():
        async for chunk in _graph.download_attachment(user, message_id, att_id):
            yield chunk
    return StreamingResponse(iter_stream(), media_type="application/octet-stream")


def _default_banner() -> str:
    return (
        "<div style=\"border:1px solid #f00;background:#fee;padding:12px;margin-bottom:12px;\">"
        "<strong>Security Notice:</strong> An attachment was removed from this email during scanning."
        " If you believe this is an error, please contact your security team."
        "</div>"
    )


@connector.item_action
async def item_action_handler(scan_event_queue_info: ScanRequestModel) -> StatusResponse:
    if not _actions_enabled():
        return StatusResponse(status=StatusResponseEnum.NOTHING, message="actions_disabled")
    parsed = _parse_m365_uri(scan_event_queue_info.location)
    if not parsed:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="unsupported_location", description=scan_event_queue_info.location)
    if _graph is None:
        return StatusResponse(status=StatusResponseEnum.ERROR, message="graph_not_configured")
    user, mid, att_id = parsed
    try:
        # 1) Delete attachment
        await _graph.delete_attachment(user, mid, att_id)

        # 2) Subject tag and banner (if configured)
        body_info = await _graph.fetch_message_body(user, mid)
        subject = body_info.get("subject") or ""
        body = body_info.get("body") or {}
        content_type = (body.get("contentType") or "html").lower()
        content = body.get("content") or ""
        # Prepend banner (convert to html if needed)
        banner = config.banner_html or _default_banner()
        if content_type != "html":
            # wrap plaintext in simple html
            content = f"<pre style='white-space:pre-wrap'>{content}</pre>"
        new_html = banner + content
        await _graph.patch_message_body_html(user, mid, new_html)
        # Subject tag
        if config.subject_tag_prefix:
            try:
                new_subj = f"{config.subject_tag_prefix}{subject}"
                # reuse patch call for subject
                token = await _graph.token()
                url = f"https://graph.microsoft.com/v1.0/users/{user}/messages/{mid}"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.patch(url, json={"subject": new_subj}, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
                    r.raise_for_status()
            except Exception:
                pass

        # 3) Move to quarantine folder if set
        if config.action_move_folder:
            try:
                folder_id = await _graph.find_or_create_folder(user, config.action_move_folder)
                await _graph.move_message(user, mid, folder_id)
            except Exception as e:
                dsx_logging.warning(f"Move to folder failed: {e}")

        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="action_applied")
    except Exception as e:
        dsx_logging.error(f"Item action failed: {e}", exc_info=True)
        return StatusResponse(status=StatusResponseEnum.ERROR, message="action_failed", description=str(e))


@connector.full_scan
async def full_scan_handler(limit: int | None = None) -> StatusResponse:
    result = await _delta_runner(limit=limit)
    status = result.get("status")
    if status != "success":
        message = result.get("message") or "delta_runner_failed"
        return StatusResponse(status=StatusResponseEnum.ERROR, message=message, description=str(result.get("details")))
    desc = f"enqueued={result.get('enqueued', 0)}"
    if limit:
        desc = f"{desc} limit={limit}"
    return StatusResponse(status=StatusResponseEnum.SUCCESS, message="delta_runner_started", description=desc)


# Webhook GET validation (Graph handshake)
@connector_api.get(f"/{config.name}/webhook/event")
async def webhook_validation(request: Request):
    token = request.query_params.get("validationToken") or request.query_params.get("validationtoken")
    if token:
        return Response(content=token, media_type="text/plain", status_code=200)
    return Response(status_code=400)


@connector.shutdown
async def shutdown_event():
    try:
        global _subs_task
        if _subs_task is not None:
            _subs_task.cancel()
    except Exception:
        pass
    try:
        global _delta_task
        if _delta_task is not None:
            _delta_task.cancel()
    except Exception:
        pass
