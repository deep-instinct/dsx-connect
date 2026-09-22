from __future__ import annotations

from typing import Any


class ScanDomain:
    """Scan request endpoints."""

    def __init__(self, core_api):
        self._api = core_api

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._api.post_scan_request(payload)

    async def request_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._api.post_scan_request_batch(payload)

    async def enqueue_done(self, job_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._api.post_enqueue_done(job_id, payload)
