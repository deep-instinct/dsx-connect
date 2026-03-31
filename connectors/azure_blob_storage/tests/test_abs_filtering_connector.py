import pytest

pytest.importorskip("azure.storage.blob")

from shared.models.connector_models import ScanRequestModel


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    import connectors.azure_blob_storage.azure_blob_storage_connector as ac

    ac.config.asset = "container-a"
    ac.config.filter = "sub1/** -tmp"

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req.location)

    monkeypatch.setattr(ac.abs_client, "is_configured", lambda: True)
    monkeypatch.setattr(ac.connector, "scan_file_request", fake_scan)

    def fake_keys(container, base_prefix: str = "", filter_str: str = "", page_size=None):
        yield {"Key": "sub1/a.txt"}
        yield {"Key": "sub1/tmp/skip.txt"}
        yield {"Key": "sub2/z.txt"}

    monkeypatch.setattr(ac.abs_client, "keys", fake_keys)

    resp = await ac.full_scan_handler()
    assert resp.status.value == "success"
    # Excludes applied, only sub1 non-tmp included
    assert calls == ["sub1/a.txt"]


@pytest.mark.asyncio
async def test_full_scan_batch_filters(monkeypatch):
    import connectors.azure_blob_storage.azure_blob_storage_connector as ac

    ac.config.asset = "container-a"
    ac.config.filter = "sub1/** -tmp"

    batch_calls = []

    async def fake_scan_batch(reqs, batch_size=None):
        batch_calls.append(([r.location for r in reqs], batch_size))
        from shared.models.status_responses import StatusResponse, StatusResponseEnum
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    async def fake_caps():
        return {"enabled": True, "default_size": 2, "max_size": 10}

    monkeypatch.setattr(ac.abs_client, "is_configured", lambda: True)
    monkeypatch.setattr(ac.connector, "scan_file_request_batch", fake_scan_batch)
    monkeypatch.setattr(ac.connector, "get_core_scan_batch_capabilities", fake_caps)

    def fake_keys(container, base_prefix: str = "", filter_str: str = "", page_size=None):
        yield {"Key": "sub1/a.txt"}
        yield {"Key": "sub1/b.txt"}
        yield {"Key": "sub1/tmp/skip.txt"}
        yield {"Key": "sub2/z.txt"}

    monkeypatch.setattr(ac.abs_client, "keys", fake_keys)

    resp = await ac.full_scan_handler(batch=True, batch_size=2)
    assert resp.status.value == "success"
    assert batch_calls == [(["sub1/a.txt", "sub1/b.txt"], 2)]
