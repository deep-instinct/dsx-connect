import pytest

import connectors.sharepoint.sharepoint_connector as spc
from shared.models.connector_models import ScanRequestModel


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    # Fake recursive iterator returning files with paths
    async def fake_iter(base):
        yield {"id": "1", "path": "sub1/a.txt"}
        yield {"id": "2", "path": "sub1/deep/b.txt"}
        yield {"id": "3", "path": "sub2/c.txt"}

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append((req.location, req.metainfo))

    spc.config.filter = "sub1/*"
    spc.config.asset = "root"
    monkeypatch.setattr(spc.sp_client, "iter_files_recursive", fake_iter)
    monkeypatch.setattr(spc.connector, "scan_file_request", fake_scan)

    resp = await spc.full_scan_handler()
    assert resp.status.value == "success"
    assert [c[0] for c in calls] == ["1"]
    assert [c[1] for c in calls] == ["sub1/a.txt"]

