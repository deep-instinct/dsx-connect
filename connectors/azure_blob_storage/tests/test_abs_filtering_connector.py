import pytest

pytest.importorskip("azure.storage.blob")

from shared.models.connector_models import ScanRequestModel, ItemActionEnum


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    import connectors.azure_blob_storage.azure_blob_storage_connector as ac

    ac.config.asset = "container-a"
    ac.config.filter = "sub1/** -tmp"

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req.location)
        from shared.models.status_responses import StatusResponse, StatusResponseEnum
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

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


@pytest.mark.asyncio
async def test_item_action_movetag_uses_requested_destination_filename(monkeypatch):
    import connectors.azure_blob_storage.azure_blob_storage_connector as ac

    ac.config.asset_container = "container-a"
    ac.config.item_action = ItemActionEnum.NOTHING

    calls = []

    monkeypatch.setattr(ac.abs_client, "key_exists", lambda container, key: True)
    monkeypatch.setattr(
        ac.abs_client,
        "move_blob",
        lambda src_container, src_key, dest_container, dest_key: calls.append(("move", src_container, src_key, dest_container, dest_key)) or True,
    )
    monkeypatch.setattr(
        ac.abs_client,
        "tag_blob",
        lambda container, key, tags=None: calls.append(("tag", container, key, tags)) or True,
    )

    request = ScanRequestModel(
        location="scan/eicar.txt",
        metainfo="container-a/scan/eicar.txt",
        requested_action={
            "type": "movetag",
            "destination": {"path": "quarantine", "filename": "eicar.txt_c23bbf85bc"},
            "tags": {"Verdict": "Malicious"},
        },
    )

    resp = await ac.item_action_handler(request)

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert calls == [
        ("tag", "container-a", "scan/eicar.txt", {"Verdict": "Malicious"}),
        ("move", "container-a", "scan/eicar.txt", "container-a", "quarantine/eicar.txt_c23bbf85bc"),
    ]
