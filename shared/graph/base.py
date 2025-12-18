from __future__ import annotations

import asyncio
import base64
import importlib
import json
import time
from typing import Optional, Sequence, Tuple

import httpx

from shared.dsx_logging import dsx_logging


class MSGraphClientBase:
    """Minimal wrapper around MSAL + httpx for Microsoft Graph."""

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        *,
        authority: str = "https://login.microsoftonline.com",
        verify: httpx._types.VerifyTypes = True,
        timeout: float = 30.0,
        log_token_claims: bool = False,
    ):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._authority = authority.rstrip("/")
        self._verify = verify
        self._timeout = timeout
        self._log_token_claims = log_token_claims

        self._msal_app = None
        self._client_session: Optional[httpx.AsyncClient] = None
        self._token_cache: dict[Tuple[str, ...], Tuple[str, float]] = {}
        self._claims_logged_scopes: set[Tuple[str, ...]] = set()

    # ---------------------- MSAL helpers ----------------------
    def _ensure_msal_app(self):
        if self._msal_app is None:
            msal = importlib.import_module("msal")
            self._msal_app = msal.ConfidentialClientApplication(
                self._client_id,
                authority=f"{self._authority}/{self._tenant_id}",
                client_credential=self._client_secret,
            )

    async def get_access_token(self, scopes: Optional[Sequence[str]] = None) -> str:
        """Acquire (and cache) an access token for the requested scopes."""
        scopes_tuple = tuple(scopes or ["https://graph.microsoft.com/.default"])
        now = time.time()
        cached = self._token_cache.get(scopes_tuple)
        if cached and now < cached[1] - 60:  # 60s early refresh window
            return cached[0]

        self._ensure_msal_app()

        def _acquire():
            return self._msal_app.acquire_token_for_client(scopes=list(scopes_tuple))

        result = await asyncio.to_thread(_acquire)
        if "access_token" not in result:
            raise RuntimeError(result.get("error_description") or str(result))

        token = result["access_token"]
        expires_in = float(result.get("expires_in", 3600))
        self._token_cache[scopes_tuple] = (token, now + expires_in)

        if self._log_token_claims and scopes_tuple not in self._claims_logged_scopes:
            try:
                hdr, claims = self._decode_jwt(token)
                dsx_logging.info(
                    "Graph token claims: aud=%s appid=%s tid=%s scopes=%s",
                    claims.get("aud"),
                    claims.get("appid"),
                    claims.get("tid"),
                    claims.get("roles") or claims.get("scp"),
                )
                self._claims_logged_scopes.add(scopes_tuple)
            except Exception:
                pass
        return token

    @staticmethod
    def _decode_jwt(token: str) -> tuple[dict, dict]:
        """Decode a JWT without verification (for logging claims only)."""
        header_b64, payload_b64, _ = token.split(".")

        def _pad(b: str) -> bytes:
            return base64.urlsafe_b64decode(b + "===")

        header = json.loads(_pad(header_b64).decode("utf-8"))
        payload = json.loads(_pad(payload_b64).decode("utf-8"))
        return header, payload

    # ---------------------- HTTP helpers ----------------------
    async def get_client(self) -> httpx.AsyncClient:
        if self._client_session is None:
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            self._client_session = httpx.AsyncClient(
                verify=self._verify,
                timeout=self._timeout,
                limits=limits,
                http2=True,
            )
        return self._client_session

    async def close(self):
        if self._client_session is not None:
            await self._client_session.aclose()
            self._client_session = None

    def graph_url(self, path: str) -> str:
        return f"{self.GRAPH_BASE}/{path.lstrip('/')}"

    async def auth_headers(
        self,
        scopes: Optional[Sequence[str]] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        token = await self.get_access_token(scopes)
        headers = {"Authorization": f"Bearer {token}"}
        if extra:
            headers.update(extra)
        return headers
