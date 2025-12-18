import pytest

pytest.importorskip("google.cloud.storage")

from shared.models.connector_models import ScanRequestModel


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.filter = "sub1/*"

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req.location)

    monkeypatch.setattr(gc.connector, "scan_file_request", fake_scan)

    def fake_keys(bucket, base_prefix: str = "", filter_str=""):
        yield {"Key": "sub1/a.txt"}
        yield {"Key": "sub1/deep/b.txt"}
        yield {"Key": "sub2/c.txt"}

    monkeypatch.setattr(gc.gcs_client, "keys", fake_keys)

    resp = await gc.full_scan_handler()
    assert resp.status.value == "success"
    # Only direct children under sub1/* are included
    assert calls == ["sub1/a.txt"]
