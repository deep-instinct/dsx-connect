from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Mapping, Optional

import httpx
import requests

from .exceptions import DiannaApiError, DSXConnectCoreApiError
from .models import AnalyzeFromSiemResponse, DiannaResultResponse

API_PREFIX = "/dsx-connect/api/v1"
TERMINAL_STATUSES = {"SUCCESS", "FAILED", "ERROR", "CANCELLED"}
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class DiannaApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8586", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{API_PREFIX}{path}"

    @staticmethod
    def _json_or_text(res: requests.Response) -> Any:
        try:
            return res.json()
        except Exception:
            return {"raw": res.text}

    def analyze_from_siem(
        self,
        *,
        scan_request_task_id: Optional[str] = None,
        connector_uuid: Optional[str] = None,
        connector_url: Optional[str] = None,
        location: Optional[str] = None,
        metainfo: Optional[str] = None,
        archive_password: Optional[str] = None,
    ) -> AnalyzeFromSiemResponse:
        body = {
            "scan_request_task_id": scan_request_task_id,
            "connector_uuid": connector_uuid,
            "connector_url": connector_url,
            "location": location,
            "metainfo": metainfo,
            "archive_password": archive_password,
        }
        body = {k: v for k, v in body.items() if v is not None}

        if "scan_request_task_id" not in body and not (
            ("connector_uuid" in body or "connector_url" in body) and "location" in body
        ):
            raise DiannaApiError(
                "provide scan_request_task_id OR (connector_uuid/connector_url and location)"
            )

        try:
            res = requests.post(self._url("/dianna/analyze-from-siem"), json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DiannaApiError(f"request failed: {exc}") from exc

        payload = self._json_or_text(res)
        if not res.ok:
            raise DiannaApiError(
                f"HTTP {res.status_code} from analyze-from-siem",
                status_code=res.status_code,
                payload=payload,
            )
        return payload if isinstance(payload, dict) else {"result": payload}

    def get_result(self, analysis_id: str) -> DiannaResultResponse:
        try:
            res = requests.get(self._url(f"/dianna/result/{analysis_id}"), timeout=self.timeout)
        except requests.RequestException as exc:
            raise DiannaApiError(f"request failed: {exc}") from exc

        payload = self._json_or_text(res)
        if not res.ok:
            hint = None
            if res.status_code == 404 and UUID_RE.match(str(analysis_id)):
                hint = "analysis_id looks like UUID; pass DIANNA analysisId, not dianna_analysis_task_id"
            raise DiannaApiError(
                f"HTTP {res.status_code} from get-result",
                status_code=res.status_code,
                payload={"detail": payload, "hint": hint} if hint else payload,
            )
        return payload if isinstance(payload, dict) else {"result": payload}

    def get_result_by_task_id(self, dianna_analysis_task_id: str) -> DiannaResultResponse:
        try:
            res = requests.get(
                self._url(f"/dianna/result/by-task/{dianna_analysis_task_id}"),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DiannaApiError(f"request failed: {exc}") from exc

        payload = self._json_or_text(res)
        if not res.ok:
            raise DiannaApiError(
                f"HTTP {res.status_code} from get-result-by-task-id",
                status_code=res.status_code,
                payload=payload,
            )
        return payload if isinstance(payload, dict) else {"result": payload}

    def poll_result(
        self,
        analysis_id: str,
        *,
        attempts: int = 30,
        sleep_seconds: float = 2.0,
    ) -> DiannaResultResponse:
        attempts = max(1, int(attempts))
        sleep_seconds = max(0.0, float(sleep_seconds))

        last: DiannaResultResponse = {}
        for i in range(1, attempts + 1):
            result = self.get_result(analysis_id)
            last = result
            status = str((result.get("result") or {}).get("status", "")).upper()
            if status in TERMINAL_STATUSES:
                return result
            if i < attempts:
                time.sleep(sleep_seconds)
        return last

    def poll_result_by_task_id(
        self,
        dianna_analysis_task_id: str,
        *,
        attempts: int = 30,
        sleep_seconds: float = 2.0,
    ) -> DiannaResultResponse:
        attempts = max(1, int(attempts))
        sleep_seconds = max(0.0, float(sleep_seconds))

        last: DiannaResultResponse = {}
        for i in range(1, attempts + 1):
            result = self.get_result_by_task_id(dianna_analysis_task_id)
            last = result
            status = str(result.get("status", "")).lower()
            if status in {"success", "accepted"}:
                return result
            if i < attempts:
                time.sleep(sleep_seconds)
        return last


class DSXConnectCoreApiClient:
    """Async client for DSX-Connect core APIs used by connector framework."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 20.0,
        verify: bool | str = True,
        auth_header_builder: Callable[[str, str, bytes | None], Mapping[str, str] | None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.verify = verify
        self.auth_header_builder = auth_header_builder

    def _url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{API_PREFIX}{path}"

    @staticmethod
    def _json_or_text(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}

    async def _request(
        self,
        *,
        method: str,
        path: str,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        use_auth: bool = False,
        timeout: float | None = None,
    ) -> Any:
        url = self._url(path)
        req_headers = dict(headers or {})

        content: bytes | None = None
        if json_body is not None:
            content = json.dumps(json_body, separators=(",", ":")).encode()
        if use_auth and self.auth_header_builder:
            extra = self.auth_header_builder(method.upper(), url, content)
            if extra:
                req_headers.update(dict(extra))

        try:
            async with httpx.AsyncClient(verify=self.verify, timeout=timeout or self.timeout) as client:
                if content is not None:
                    resp = await client.request(method, url, content=content, headers=req_headers or None)
                else:
                    resp = await client.request(method, url, headers=req_headers or None)
        except httpx.RequestError as exc:
            raise DSXConnectCoreApiError(f"request failed: {exc}") from exc

        payload = self._json_or_text(resp)
        if resp.status_code >= 400:
            raise DSXConnectCoreApiError(
                f"HTTP {resp.status_code} from {method.upper()} {path}",
                status_code=resp.status_code,
                payload=payload,
            )
        return payload

    async def get_config(self) -> dict[str, Any]:
        payload = await self._request(method="GET", path="/config", timeout=5.0)
        return payload if isinstance(payload, dict) else {}

    async def get_connection_test(self) -> dict[str, Any]:
        payload = await self._request(method="GET", path="/connection/test", timeout=5.0)
        return payload if isinstance(payload, dict) else {}

    async def post_scan_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = await self._request(
            method="POST",
            path="/scan/request",
            json_body=payload,
            use_auth=True,
        )
        return out if isinstance(out, dict) else {"result": out}

    async def post_scan_request_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = await self._request(
            method="POST",
            path="/scan/request_batch",
            json_body=payload,
            use_auth=True,
        )
        return out if isinstance(out, dict) else {"result": out}

    async def post_register_connector(
        self,
        payload: dict[str, Any],
        *,
        enrollment_token: str | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Enrollment-Token": enrollment_token} if enrollment_token else None
        out = await self._request(
            method="POST",
            path="/connectors/register",
            json_body=payload,
            headers=headers,
        )
        return out if isinstance(out, dict) else {"result": out}

    async def delete_unregister_connector(self, connector_uuid: str) -> dict[str, Any]:
        out = await self._request(
            method="DELETE",
            path=f"/connectors/unregister/{connector_uuid}",
            use_auth=True,
        )
        return out if isinstance(out, dict) else {"result": out}

    async def post_enqueue_done(self, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        out = await self._request(
            method="POST",
            path=f"/scan/jobs/{job_id}/enqueue_done",
            json_body=payload or {},
            use_auth=True,
        )
        return out if isinstance(out, dict) else {"result": out}


from .domains import (
    ConnectorsDomain,
    CoreDomain,
    DiannaDomain,
    ResultsDomain,
    ScanDomain,
    SseDomain,
)


class DSXConnectClient:
    """Root SDK client with domain-oriented sub-clients (mirrors API routers)."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8586",
        timeout: float = 20.0,
        verify: bool | str = True,
        auth_header_builder: Callable[[str, str, bytes | None], Mapping[str, str] | None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.verify = verify
        self.auth_header_builder = auth_header_builder

        self._core_api = DSXConnectCoreApiClient(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=self.verify,
            auth_header_builder=self.auth_header_builder,
        )
        self._dianna_api = DiannaApiClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

        self.core = CoreDomain(self._core_api)
        self.scan = ScanDomain(self._core_api)
        self.connectors = ConnectorsDomain(self._core_api)
        self.results = ResultsDomain()
        self.sse = SseDomain()
        self.dianna = DiannaDomain(self._dianna_api)

    # Backward-compatible convenience accessors
    @property
    def core_api(self) -> DSXConnectCoreApiClient:
        return self._core_api

    @property
    def dianna_api(self) -> DiannaApiClient:
        return self._dianna_api
