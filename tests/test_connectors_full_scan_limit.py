from contextlib import asynccontextmanager
from uuid import uuid4

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


def test_full_scan_forwards_limit_query(monkeypatch):
    app = FastAPI()
    app.include_router(connectors_router.router)

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
        async def post(self, path, json_body=None, headers=None, params=None):
            captured["path"] = str(path)
            captured["params"] = dict(params or {})
            return _FakeResponse({"status": "success", "message": "full scan triggered"})

    @asynccontextmanager
    async def fake_async_client(_):
        yield _StubClient()

    monkeypatch.setattr(connectors_router, "get_async_connector_client", fake_async_client, raising=True)

    with TestClient(app) as client:
        r = client.post(f"/dsx-connect/api/v1/connectors/full_scan/{cid}?limit=5")
        assert r.status_code == 202 or r.status_code == 200
        # The route returns StatusResponse; we only need to verify param forwarding
        assert captured.get("params", {}).get("limit") == "5"

