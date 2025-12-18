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

    monkeypatch.setattr(ac.connector, "scan_file_request", fake_scan)

    def fake_keys(container, base_prefix: str = "", filter_str: str = ""):
        yield {"Key": "sub1/a.txt"}
        yield {"Key": "sub1/tmp/skip.txt"}
        yield {"Key": "sub2/z.txt"}

    monkeypatch.setattr(ac.abs_client, "keys", fake_keys)

    resp = await ac.full_scan_handler()
    assert resp.status.value == "success"
    # Excludes applied, only sub1 non-tmp included
    assert calls == ["sub1/a.txt"]
