import time, os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt  # PyJWT

from fastapi import HTTPException, Request, Depends
from dsx_connect.config import get_auth_config
from dsx_connect.app.auth_tokens import verify_access_token_opaque


def auth_enabled() -> bool:
    cfg = get_auth_config()
    return bool(getattr(cfg, "enabled", False))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def verify_enrollment_token(token: Optional[str]) -> bool:
    if not token:
        return False
    cfg = get_auth_config()
    # Support single token or CSV via env override DSXCONNECT_AUTH__ENROLLMENT_TOKENS
    try:
        multi = os.getenv("DSXCONNECT_AUTH__ENROLLMENT_TOKENS")
        if multi:
            allowed = [t.strip() for t in multi.split(",") if t.strip()]
            if token in allowed:
                return True
    except Exception:
        pass
    return token == cfg.enrollment_token


def issue_access_token(connector_uuid: Optional[str] = None) -> dict:
    cfg = get_auth_config()
    iat = _now()
    exp = iat + timedelta(seconds=int(getattr(cfg, "jwt_ttl", 900) or 900))
    payload = {
        "iss": getattr(cfg, "jwt_issuer", "dsx-connect") or "dsx-connect",
        "aud": getattr(cfg, "jwt_audience", "dsx-connect") or "dsx-connect",
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
        "role": "connector",
    }
    if connector_uuid:
        payload["sub"] = connector_uuid
    token = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": int((exp - iat).total_seconds()),
    }


def verify_access_token(bearer: str) -> dict:
    cfg = get_auth_config()
    return jwt.decode(
        bearer,
        cfg.jwt_secret,
        algorithms=["HS256"],
        audience=(getattr(cfg, "jwt_audience", "dsx-connect") or "dsx-connect"),
        issuer=(getattr(cfg, "jwt_issuer", "dsx-connect") or "dsx-connect"),
        options={"require": ["exp", "iat", "aud", "iss"]},
    )


def _bearer_from_auth_header(request: Request) -> Optional[str]:
    try:
        hdr = request.headers.get("Authorization", "").strip()
        if not hdr:
            return None
        if hdr.lower().startswith("bearer "):
            return hdr[7:].strip()
        return None
    except Exception:
        return None


async def require_connector_bearer(request: Request) -> dict | None:
    """When auth is enabled, validate Authorization: Bearer and return claims.

    - On missing/invalid token, raise HTTP 401 with WWW-Authenticate: Bearer.
    - On role/audience/issuer mismatch, verify_access_token will raise.
    - When auth is disabled, returns None and performs no checks.
    """
    if not auth_enabled():
        return None
    token = _bearer_from_auth_header(request)
    if not token:
        # Missing bearer
        raise HTTPException(status_code=401, detail="missing_bearer_token", headers={"WWW-Authenticate": "Bearer"})
    # Try opaque token (preferred) against Redis
    try:
        r = getattr(request.app.state, "redis", None)
        claims = None
        if r is not None:
            claims = await verify_access_token_opaque(r, token)
            return claims
    except Exception as e:
        # fall through to JWT verify
        pass
    # Fallback: JWT
    try:
        claims = verify_access_token(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid_token: {e}", headers={"WWW-Authenticate": "Bearer"})
    # Minimal role check
    role = claims.get("role")
    if role and role != "connector":
        # Role present but not connector → forbidden
        raise HTTPException(status_code=403, detail="forbidden: role_mismatch")
    return claims


def enrollment_token_from_request(request: Request) -> Optional[str]:
    # Accept either X-Enrollment-Token header or Authorization: Bearer <token>
    token = request.headers.get("X-Enrollment-Token")
    if token:
        return token.strip()
    bearer = _bearer_from_auth_header(request)
    return bearer
