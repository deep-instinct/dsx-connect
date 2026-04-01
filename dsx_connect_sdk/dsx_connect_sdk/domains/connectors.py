from __future__ import annotations

from typing import Any


class ConnectorsDomain:
    """Connector registration/lifecycle endpoints."""

    def __init__(self, core_api):
        self._api = core_api

    async def register(self, payload: dict[str, Any], *, enrollment_token: str | None = None) -> dict[str, Any]:
        return await self._api.post_register_connector(payload, enrollment_token=enrollment_token)

    async def unregister(self, connector_uuid: str) -> dict[str, Any]:
        return await self._api.delete_unregister_connector(connector_uuid)
