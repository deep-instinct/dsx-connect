from typing import Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from pydantic_settings import BaseSettings
from shared.auth.hmac import verify_hmac, make_hmac_header


class ConnectorAuthSettings(BaseSettings):
    enabled: bool = False
    hmac_key_id: Optional[str] = None
    hmac_secret: Optional[str] = None
    clock_skew_seconds: int = 60

    class Config:
        env_prefix = "DSXCONNECTOR_AUTH__"
        case_sensitive = False


_settings = ConnectorAuthSettings()
_runtime_kid: Optional[str] = None
_runtime_secret: Optional[str] = None

def set_runtime_hmac_credentials(key_id: str, secret: str) -> None:
    global _runtime_kid, _runtime_secret
    _runtime_kid, _runtime_secret = key_id, secret


def reload_settings() -> None:
    """Reload connector auth settings from environment (after .env load)."""
    global _settings
    _settings = ConnectorAuthSettings()


def auth_enabled() -> bool:
    """Return whether connector-side DSX-HMAC verification is enabled."""
    return bool(_settings.enabled)


async def require_dsx_hmac(request: Request) -> None:
    """Verify DSX-HMAC for dsx-connect → connector calls when enabled.

    - Disabled by default and in local/docker-compose scenarios.
    - On failure, raises 401 with concise reason.
    """
    if not _settings.enabled:
        return

    def lookup(kid: str) -> str | None:
        rk = _runtime_kid or _settings.hmac_key_id or ""
        rs = _runtime_secret or _settings.hmac_secret or ""
        if kid == rk:
            return rs
        return None

    try:
        header = request.headers.get("Authorization", "")
        body = await request.body()
        path_q = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        verify_hmac(request.method, path_q, body, header, lookup, _settings.clock_skew_seconds)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    return None


def get_runtime_hmac_credentials() -> tuple[str | None, str | None]:
    """Return the current HMAC credentials (runtime overrides beat static env)."""
    rk = _runtime_kid or _settings.hmac_key_id
    rs = _runtime_secret or _settings.hmac_secret
    return rk, rs


def build_outbound_auth_header(method: str, url: str, body: bytes | None) -> str | None:
    """Best-effort Authorization header for connector → dsx-connect calls.

    Returns None when credentials are unavailable (e.g., local docker-compose).
    """
    kid, secret = get_runtime_hmac_credentials()
    if not kid or not secret:
        return None
    parts = urlsplit(url)
    path_q = parts.path + (f"?{parts.query}" if parts.query else "")
    return make_hmac_header(kid, secret, method.upper(), path_q, body)
