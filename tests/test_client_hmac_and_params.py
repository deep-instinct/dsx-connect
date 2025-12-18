import os
import types
import importlib
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import pytest


class _DummyResponse:
    def __init__(self, method: str, url: str, headers: dict):
        self.status_code = 200
        self.method = method
        self.url = url
        self.headers = headers

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


class _StubAsyncClient:
    def __init__(self, *_, **__):
        self.last = None

    async def aclose(self):
        return None

    async def request(self, method, url, content=None, headers=None):
        self.last = {"method": method, "url": url, "headers": headers or {}}
        return _DummyResponse(method, url, headers or {})


@pytest.mark.asyncio
async def test_async_client_params_in_url_without_hmac(monkeypatch):
    # Reload config and client modules to pick up env
    import dsx_connect.config as cfg
    importlib.reload(cfg)

    import dsx_connect.connectors.client as client_mod
    # Patch httpx.AsyncClient used in the client module
    stub_httpx = types.SimpleNamespace(AsyncClient=_StubAsyncClient)
    monkeypatch.setattr(client_mod, "httpx", stub_httpx, raising=True)
    importlib.reload(client_mod)  # ensure DEV computed from reloaded config

    # Build a simple URL base (no HMAC creds provided; allowed in dev)
    base = "http://svc:9000"

    # Use the async contextmanager to get a client and perform GET with params
    async with client_mod.get_async_connector_client(base) as c:
        resp = await c.get("repo_check", params={"preview": 5, "q": ["a", "b"]})
        # Validate URL contains query params (order not guaranteed)
        parsed = urlsplit(resp.url)
        qs = parse_qs(parsed.query)
        assert qs.get("preview") == ["5"]
        assert qs.get("q") == ["a", "b"]
        # Without HMAC creds, Authorization header should not be present
        assert "Authorization" not in resp.headers


@pytest.mark.asyncio
async def test_async_client_params_and_hmac(monkeypatch):
    import dsx_connect.config as cfg
    importlib.reload(cfg)

    import dsx_connect.connectors.client as client_mod
    stub_httpx = types.SimpleNamespace(AsyncClient=_StubAsyncClient)
    monkeypatch.setattr(client_mod, "httpx", stub_httpx, raising=True)
    importlib.reload(client_mod)

    # Provide connector with HMAC creds
    conn = SimpleNamespace(url="http://svc:9000", hmac_key_id="kid", hmac_secret="secret")

    async with client_mod.get_async_connector_client(conn) as c:
        resp = await c.get("repo_check", params={"preview": 3})
        parsed = urlsplit(resp.url)
        qs = parse_qs(parsed.query)
        assert qs.get("preview") == ["3"]
        # In prod, Authorization header must be set
        auth = resp.headers.get("Authorization", "")
        assert auth.startswith("DSX-HMAC ")
