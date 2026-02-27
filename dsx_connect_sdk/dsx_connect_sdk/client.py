from __future__ import annotations

import re
import time
from typing import Any, Optional

import requests

from .exceptions import DiannaApiError
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
