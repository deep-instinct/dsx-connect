import asyncio
from unittest.mock import MagicMock, patch

import httpx
import pytest
import sys
import types

from connectors.sharepoint.config import SharepointConnectorConfig
from connectors.sharepoint.sharepoint_client import SharePointClient, GRAPH_BASE


def _response(status_code, url, **kwargs):
    return httpx.Response(status_code, request=httpx.Request("GET", url), **kwargs)


@pytest.mark.asyncio
async def test_token_acquisition_and_list(monkeypatch):
    cfg = SharepointConnectorConfig(
        sp_tenant_id="tenant",
        sp_client_id="client",
        sp_client_secret="secret",
        sp_hostname="contoso.sharepoint.com",
        sp_site_path="SiteA",
    )
    client = SharePointClient(cfg)

    # Patch MSAL acquire_token_for_client
    class DummyMSAL:
        def __init__(self, *args, **kwargs):
            pass

        def acquire_token_for_client(self, scopes=None):
            return {"access_token": "tok", "expires_in": 3600}

    # stub msal module
    monkeypatch.setitem(sys.modules, "msal", types.SimpleNamespace(ConfidentialClientApplication=DummyMSAL))

    # Mock httpx responses for site, drive, and list children
    async def fake_get(self, url, headers=None, follow_redirects=False):
        if url.startswith(f"{GRAPH_BASE}/sites/") and "?$select=" in url:
            return _response(200, url, json={"id": "site-id"})
        if url == f"{GRAPH_BASE}/sites/site-id/drive":
            return _response(200, url, json={"id": "drive-id"})
        if url.startswith(f"{GRAPH_BASE}/drives/drive-id/root/children"):
            return _response(200, url, json={"value": [{"id": "1", "name": "a.txt"}]})
        return _response(404, url)

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        items = await client.list_files("")
        assert items and items[0]["name"] == "a.txt"


@pytest.mark.asyncio
async def test_download_by_id(monkeypatch):
    cfg = SharepointConnectorConfig(
        sp_tenant_id="tenant",
        sp_client_id="client",
        sp_client_secret="secret",
        sp_hostname="contoso.sharepoint.com",
        sp_site_path="SiteA",
    )
    client = SharePointClient(cfg)

    class DummyMSAL:
        def __init__(self, *args, **kwargs):
            pass

        def acquire_token_for_client(self, scopes=None):
            return {"access_token": "tok", "expires_in": 3600}

    monkeypatch.setitem(sys.modules, "msal", types.SimpleNamespace(ConfidentialClientApplication=DummyMSAL))

    async def fake_get(self, url, headers=None, follow_redirects=False):
        if url.startswith(f"{GRAPH_BASE}/sites/") and "?$select=" in url:
            return _response(200, url, json={"id": "site-id"})
        if url == f"{GRAPH_BASE}/sites/site-id/drive":
            return _response(200, url, json={"id": "drive-id"})
        if url == f"{GRAPH_BASE}/drives/drive-id/items/abc/content":
            return _response(200, url, content=b"hello")
        return _response(404, url)

    with patch.object(httpx.AsyncClient, "get", new=fake_get):
        resp = await client.download_file("abc")
        assert resp.status_code == 200
        assert resp.content == b"hello"


@pytest.mark.asyncio
async def test_move_creates_folders_and_patches(monkeypatch):
    cfg = SharepointConnectorConfig(
        sp_tenant_id="tenant",
        sp_client_id="client",
        sp_client_secret="secret",
        sp_hostname="contoso.sharepoint.com",
        sp_site_path="SiteA",
    )
    client = SharePointClient(cfg)

    class DummyMSAL:
        def __init__(self, *args, **kwargs):
            pass

        def acquire_token_for_client(self, scopes=None):
            return {"access_token": "tok", "expires_in": 3600}

    monkeypatch.setitem(sys.modules, "msal", types.SimpleNamespace(ConfidentialClientApplication=DummyMSAL))

    calls = {"post": [], "get": [], "patch": []}

    async def fake_get(self, url, headers=None, follow_redirects=False):
        calls["get"].append(url)
        if url.startswith(f"{GRAPH_BASE}/sites/") and "?$select=" in url:
            return _response(200, url, json={"id": "site-id"})
        if url == f"{GRAPH_BASE}/sites/site-id/drive":
            return _response(200, url, json={"id": "drive-id"})
        # First two folder probes 404, then success on third
        if url.endswith("/root:/quarantine"):
            return _response(404, url)
        if url.endswith("/root:/quarantine/sub"):
            return _response(404, url)
        if url.endswith("/root:/quarantine/sub"):
            return _response(200, url, json={"id": "folder-id"})
        # Item content retrieve not used here
        return _response(404, url)

    async def fake_post(self, url, headers=None, json=None, content=None):
        calls["post"].append((url, json))
        # create folder returns a driveItem
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id": "folder-created"})

    async def fake_patch(self, url, headers=None, json=None):
        calls["patch"].append((url, json))
        return httpx.Response(200, request=httpx.Request("PATCH", url), json={"id": "moved-id"})

    with patch.object(httpx.AsyncClient, "get", new=fake_get), \
         patch.object(httpx.AsyncClient, "post", new=fake_post), \
         patch.object(httpx.AsyncClient, "patch", new=fake_patch):
        # Resolve item id call path: resolve_item_id uses path detection; give id directly
        res = await client.move_file("item123", "quarantine/sub")
        assert res["id"] == "moved-id"
        assert any("/children" in u for u,_ in calls["post"])  # folders created
        assert len(calls["patch"]) == 1
