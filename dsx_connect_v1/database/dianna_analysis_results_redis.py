from __future__ import annotations

import json
from typing import Optional

import redis


class DiannaAnalysisResultsRedis:
    """Redis-backed storage for DIANNA analysis task results."""

    def __init__(self, database_loc: str, retain_days: int = 90):
        self._r = redis.from_url(str(database_loc), decode_responses=True)
        self._retain_seconds = max(1, int(retain_days)) * 24 * 3600
        self._task_prefix = "dsxconnect:dianna:analysis:task:"
        self._scan_prefix = "dsxconnect:dianna:analysis:scan_request:"

    def _task_key(self, dianna_analysis_task_id: str) -> str:
        return f"{self._task_prefix}{dianna_analysis_task_id}"

    def _scan_key(self, scan_request_task_id: str) -> str:
        return f"{self._scan_prefix}{scan_request_task_id}"

    def put(self, dianna_analysis_task_id: str, payload: dict, *, scan_request_task_id: str | None = None) -> None:
        raw = json.dumps(payload, separators=(",", ":"))
        self._r.set(self._task_key(dianna_analysis_task_id), raw, ex=self._retain_seconds)
        if scan_request_task_id:
            self._r.set(self._scan_key(scan_request_task_id), raw, ex=self._retain_seconds)

    def get_by_task(self, dianna_analysis_task_id: str) -> Optional[dict]:
        raw = self._r.get(self._task_key(dianna_analysis_task_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def get_by_scan_request(self, scan_request_task_id: str) -> Optional[dict]:
        raw = self._r.get(self._scan_key(scan_request_task_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
