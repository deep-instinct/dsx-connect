import os
import secrets
import time
from typing import Optional, Tuple

from redis.asyncio import Redis

TOKEN_NAMESPACE = "dsxconnect:auth:access"


def _now() -> int:
    return int(time.time())


def _ttl(expiry_ts: int) -> int:
    return max(1, expiry_ts - _now())


async def issue_access_token_opaque(r: Optional[Redis], sub: Optional[str], ttl_seconds: int = 600) -> Tuple[str, int]:
    """Mint an opaque access token stored in Redis with TTL.

    Returns (token, expires_in_seconds).
    """
    token = secrets.token_urlsafe(32)
    exp_ts = _now() + int(ttl_seconds or 600)
    if r is not None:
        key = f"{TOKEN_NAMESPACE}:{token}"
        data = {"sub": sub or "", "exp": str(exp_ts)}
        try:
            await r.hset(key, mapping=data)
            await r.expire(key, _ttl(exp_ts))
        except Exception:
            pass
    return token, int(ttl_seconds or 600)


async def verify_access_token_opaque(r: Optional[Redis], token: str) -> dict:
    if not token:
        raise ValueError("missing_token")
    if r is None:
        raise ValueError("token_store_unavailable")
    key = f"{TOKEN_NAMESPACE}:{token}"
    data = await r.hgetall(key)
    if not data:
        raise ValueError("invalid_token")
    try:
        exp = int(data.get("exp", 0))
    except Exception:
        exp = 0
    if _now() >= exp:
        raise ValueError("expired_token")
    return {"sub": data.get("sub") or None, "exp": exp}

