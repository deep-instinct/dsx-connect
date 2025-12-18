from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

import httpx

from connectors.salesforce.config import SalesforceConnectorConfig
from shared.dsx_logging import dsx_logging


class SalesforceClient:
    """
    Lightweight Salesforce REST client focused on ContentVersion operations.
    """

    def __init__(self, cfg: SalesforceConnectorConfig):
        self._cfg = cfg
        verify: httpx._types.VerifyTypes
        if not cfg.sf_verify_tls:
            verify = False
        elif cfg.sf_ca_bundle:
            verify = cfg.sf_ca_bundle
        else:
            verify = True

        self._http = httpx.AsyncClient(timeout=cfg.sf_http_timeout, verify=verify)
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._instance_url: Optional[str] = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth helpers
    async def _ensure_token(self) -> None:
        async with self._lock:
            if self._access_token and time.time() < self._token_expiry - 30:
                return

            payload = {
                "grant_type": "password",
                "client_id": self._cfg.sf_client_id,
                "client_secret": self._cfg.sf_client_secret,
                "username": self._cfg.sf_username,
                "password": f"{self._cfg.sf_password}{self._cfg.sf_security_token or ''}",
            }
            token_url = f"{self._cfg.sf_login_url.rstrip('/')}/services/oauth2/token"
            resp = await self._http.post(token_url, data=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text if exc.response is not None else ""
                raise RuntimeError(f"Salesforce auth failed: {exc.response.status_code} {detail}") from exc

            data = resp.json()
            self._access_token = data["access_token"]
            self._instance_url = data["instance_url"].rstrip("/")
            expires_in = int(data.get("expires_in", 3600))
            self._token_expiry = time.time() + expires_in
            dsx_logging.info("Obtained Salesforce access token.")

    async def _headers(self) -> Dict[str, str]:
        await self._ensure_token()
        if not self._access_token:
            raise RuntimeError("Salesforce token unavailable")
        return {"Authorization": f"Bearer {self._access_token}"}

    def build_where_clause(self) -> str:
        clauses: List[str] = []
        base = (self._cfg.sf_where or "").strip()
        if base:
            clauses.append(base)
        asset_clause = (self._cfg.asset or "").strip()
        if asset_clause:
            clauses.append(asset_clause)
        if not clauses:
            return ""
        return " WHERE " + " AND ".join(f"({c})" if " " in c and not c.strip().startswith("(") else c for c in clauses)

    def build_query(self, limit: Optional[int] = None) -> str:
        fields = self._cfg.sf_fields or "Id, Title, FileExtension"
        query = f"SELECT {fields} FROM ContentVersion"
        query += self.build_where_clause()
        order = (self._cfg.sf_order_by or "").strip()
        if order:
            query += f" ORDER BY {order}"
        if limit and limit > 0:
            query += f" LIMIT {int(limit)}"
        return query

    # ------------------------------------------------------------------ content operations
    async def iter_content_versions(self, limit: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]:
        """Yield ContentVersion rows based on configured filters."""
        effective_limit = limit if limit is not None else self._cfg.sf_max_records
        query = self.build_query(limit=effective_limit)
        async for record in self._query(query, max_records=effective_limit):
            yield record

    async def _query(self, soql: str, max_records: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]:
        await self._ensure_token()
        if not self._instance_url:
            raise RuntimeError("Salesforce instance URL not available")

        encoded = quote_plus(soql)
        url = f"{self._instance_url}/services/data/{self._cfg.sf_api_version}/query?q={encoded}"
        headers = await self._headers()
        remaining = None
        if max_records:
            remaining = int(max_records)

        while url:
            resp = await self._http.get(url, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Salesforce query failed: {exc.response.status_code} {exc.response.text}") from exc
            payload = resp.json()
            for record in payload.get("records", []):
                yield record
                if remaining is not None:
                    remaining -= 1
                    if remaining <= 0:
                        return
            if payload.get("done"):
                return
            next_url = payload.get("nextRecordsUrl")
            if not next_url:
                return
            url = f"{self._instance_url}{next_url}"

    async def stream_content_version(self, content_version_id: str) -> AsyncIterator[bytes]:
        await self._ensure_token()
        if not self._instance_url:
            raise RuntimeError("Salesforce instance URL not available")
        headers = await self._headers()
        url = f"{self._instance_url}/services/data/{self._cfg.sf_api_version}/sobjects/ContentVersion/{content_version_id}/VersionData"

        async with self._http.stream("GET", url, headers=headers) as resp:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Salesforce download failed: {exc.response.status_code} {exc.response.text}"
                ) from exc
            async for chunk in resp.aiter_bytes():
                yield chunk

    async def repo_health(self) -> bool:
        """Basic repository health check by querying limits endpoint."""
        await self._ensure_token()
        if not self._instance_url:
            return False
        headers = await self._headers()
        url = f"{self._instance_url}/services/data/{self._cfg.sf_api_version}/limits"
        resp = await self._http.get(url, headers=headers)
        if resp.status_code == 200:
            return True
        dsx_logging.warning("Salesforce limits check failed: %s - %s", resp.status_code, resp.text)
        return False
