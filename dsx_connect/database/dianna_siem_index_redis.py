from __future__ import annotations

import json
from typing import Optional

import redis


class DiannaSiemIndexRedis:
    """Redis-backed index for malicious scan task lookups used by SIEM callbacks."""

    def __init__(self, database_loc: str, retain_days: int = 90):
        self._r = redis.from_url(str(database_loc), decode_responses=True)
        self._retain_seconds = max(1, int(retain_days)) * 24 * 3600
        self._key_prefix = "dsxconnect:dianna:siem:task:"

    def _key(self, scan_request_task_id: str) -> str:
        return f"{self._key_prefix}{scan_request_task_id}"

    def put(self, scan_request_task_id: str, payload: dict) -> None:
        self._r.set(self._key(scan_request_task_id), json.dumps(payload, separators=(",", ":")), ex=self._retain_seconds)

    def get(self, scan_request_task_id: str) -> Optional[dict]:
        raw = self._r.get(self._key(scan_request_task_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

