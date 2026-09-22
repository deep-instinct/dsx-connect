from __future__ import annotations

from typing import Any


class CoreDomain:
    """Core platform endpoints (health/config)."""

    def __init__(self, core_api):
        self._api = core_api

    async def get_config(self) -> dict[str, Any]:
        return await self._api.get_config()

    async def connection_test(self) -> dict[str, Any]:
        return await self._api.get_connection_test()
