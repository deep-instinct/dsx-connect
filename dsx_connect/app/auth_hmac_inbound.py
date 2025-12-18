from typing import Optional

from fastapi import HTTPException, Request
from shared.auth.hmac import verify_hmac
from dsx_connect.app.auth_jwt import auth_enabled
from dsx_connect.messaging.connector_keys import ConnectorKeys

KID_INDEX_PREFIX = "dsxconnect:hmac:kid"


async def _lookup_secret_by_kid(request: Request, kid: str) -> Optional[str]:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        return None
    try:
        # Resolve connector uuid from kid index
        idx_key = f"{KID_INDEX_PREFIX}:{kid}"
        uuid = await r.get(idx_key)
        if not uuid:
            return None
        if isinstance(uuid, (bytes, bytearray)):
            uuid = uuid.decode()
        cfg_key = ConnectorKeys.config(str(uuid))
        sec = await r.hget(cfg_key, "hmac_secret")
        if isinstance(sec, (bytes, bytearray)):
            sec = sec.decode()
        return sec
    except Exception:
        return None


async def require_dsx_hmac_inbound(request: Request) -> None:
    """Require DSX-HMAC on inbound connector→dsx-connect calls when auth is enabled."""
    if not auth_enabled():
        return
    header = request.headers.get("Authorization", "")

    async def _secret_lookup(kid: str) -> Optional[str]:
        return await _lookup_secret_by_kid(request, kid)

    try:
        body = await request.body()
        path_q = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        # verify_hmac expects a sync lookup; adapt with closure that fetches a cached value
        # For async Redis, prefetch secret via above helper
        secret = await _secret_lookup(_extract_kid(header))
        if not secret:
            raise HTTPException(status_code=401, detail="unknown_key_id")
        # Build a simple synchronous lookup
        def lookup(_kid: str) -> Optional[str]:
            return secret if _kid else None
        verify_hmac(request.method, path_q, body, header, lookup, skew_seconds=60)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


def _extract_kid(header: str) -> str:
    if not header or not header.startswith("DSX-HMAC "):
        return ""
    try:
        parts = dict(kv.strip().split("=", 1) for kv in header[len("DSX-HMAC "):].split(","))
        return parts.get("key_id", "")
    except Exception:
        return ""

