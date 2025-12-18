from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.models.connector_models import ConnectorInstanceModel, ConnectorStatusEnum
from dsx_connect.app.routers import connectors as connectors_router


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


@pytest.mark.parametrize("preview_value", ["5", "10"])
def test_repo_check_forwards_preview_query(monkeypatch, preview_value):
    # Build minimal app with the connectors router
    app = FastAPI()
    app.include_router(connectors_router.router)

    # Register a connector in app state (so _lookup falls back to this list)
    cid = uuid4()
    app.state.connectors = [
        ConnectorInstanceModel(
            name="fs",
            uuid=cid,
            url="http://connector:9999",
            status=ConnectorStatusEnum.READY,
        )
    ]

    captured = {}

    class _StubClient:
        async def get(self, path, headers=None, params=None):
            # Capture seen params and path; return success payload
            captured["path"] = str(path)
            captured["params"] = dict(params or {})
            return _FakeResponse({"status": "success", "message": "repo_check"})

    @asynccontextmanager
    async def fake_async_client(_):
        yield _StubClient()

    # Patch the client factory used by the route
    monkeypatch.setattr(connectors_router, "get_async_connector_client", fake_async_client, raising=True)

    with TestClient(app) as client:
        r = client.get(f"/dsx-connect/api/v1/connectors/repo_check/{cid}?preview={preview_value}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "success"
        # Ensure the route forwarded the preview query as a string
        assert captured.get("params", {}).get("preview") == preview_value

