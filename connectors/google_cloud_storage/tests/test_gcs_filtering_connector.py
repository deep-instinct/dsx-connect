import pytest

pytest.importorskip("google.cloud.storage")

from shared.models.connector_models import ItemActionEnum, ScanRequestModel


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.filter = "sub1/*"

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req.location)
        return gc.StatusResponse(status=gc.StatusResponseEnum.SUCCESS, message="ok")

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


@pytest.mark.asyncio
async def test_full_scan_batch_filters(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.filter = "sub1/*"

    batch_calls = []

    async def fake_scan_batch(reqs):
        batch_calls.append([req.location for req in reqs])
        return gc.StatusResponse(status=gc.StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(gc.connector, "scan_file_request_batch", fake_scan_batch)

    def fake_keys(bucket, base_prefix: str = "", filter_str=""):
        yield {"Key": "sub1/a.txt"}
        yield {"Key": "sub1/deep/b.txt"}
        yield {"Key": "sub2/c.txt"}

    monkeypatch.setattr(gc.gcs_client, "keys", fake_keys)

    resp = await gc.full_scan_handler(batch=True, batch_size=100)
    assert resp.status.value == "success"
    assert batch_calls == [["sub1/a.txt"]]


@pytest.mark.asyncio
async def test_asset_discovery_reports_configured_bucket_by_default(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs/sub1"
    gc.config.asset_bucket = "bucket-gcs"
    gc.config.asset_prefix_root = "sub1"
    monkeypatch.setattr(gc.gcs_client, "buckets", lambda: ["bucket-a", "bucket-b", "bucket-c"])

    resp = await gc.asset_discovery_handler(asset_type="bucket", limit=2)

    assert resp.asset_type == "bucket"
    assert resp.source == "configured_asset"
    assert resp.status == "success"
    assert [asset.selector for asset in resp.assets] == ["bucket-gcs/sub1"]
    assert resp.next_cursor is None
    assert resp.assets[0].metadata["provider"] == "gcs"
    assert resp.assets[0].metadata["kind"] == "configured_bucket_prefix"
    assert resp.assets[0].metadata["bucket"] == "bucket-gcs"
    assert resp.assets[0].metadata["prefix"] == "sub1"


@pytest.mark.asyncio
async def test_asset_discovery_lists_gcs_buckets_for_inventory_enumeration(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    monkeypatch.setattr(gc.gcs_client, "buckets", lambda: ["bucket-a", "bucket-b", "bucket-c"])

    resp = await gc.asset_discovery_handler(asset_type="bucket", source="inventory_enumeration", limit=2)

    assert resp.asset_type == "bucket"
    assert resp.source == "inventory_enumeration"
    assert resp.status == "success"
    assert [asset.selector for asset in resp.assets] == ["bucket-a", "bucket-b"]
    assert resp.next_cursor == "2"
    assert resp.assets[0].metadata["provider"] == "gcs"


@pytest.mark.asyncio
async def test_asset_discovery_reports_unsupported_asset_type(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    monkeypatch.setattr(gc.gcs_client, "buckets", lambda: ["bucket-a"])

    resp = await gc.asset_discovery_handler(asset_type="drive", limit=2)

    assert resp.unsupported is True
    assert resp.assets == []
    assert resp.message == "unsupported_asset_type:drive"


@pytest.mark.asyncio
async def test_asset_discovery_reports_bucket_listing_failure(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    def fail_buckets():
        raise RuntimeError("403 storage.buckets.list permission denied")

    monkeypatch.setattr(gc.gcs_client, "buckets", fail_buckets)

    resp = await gc.asset_discovery_handler(asset_type="bucket", source="inventory_enumeration", limit=2)

    assert resp.unsupported is False
    assert resp.source == "inventory_enumeration"
    assert resp.status == "permission_denied"
    assert resp.assets == []
    assert resp.message == "asset_discovery_failed:403 storage.buckets.list permission denied"
    assert resp.required_permission == "storage.buckets.list"


@pytest.mark.asyncio
async def test_item_action_handler_uses_requested_movetag(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.asset_bucket = "bucket-gcs"
    gc.config.item_action = ItemActionEnum.NOTHING

    calls: list[tuple] = []

    monkeypatch.setattr(gc.gcs_client, "key_exists", lambda bucket, key: True)
    monkeypatch.setattr(
        gc.gcs_client,
        "move_object",
        lambda src_bucket, src_key, dest_bucket, dest_key: calls.append(("move", src_bucket, src_key, dest_bucket, dest_key)) or True,
    )
    monkeypatch.setattr(
        gc.gcs_client,
        "tag_object",
        lambda bucket, key, tags=None: calls.append(("tag", bucket, key, tags)) or True,
    )

    resp = await gc.item_action_handler(
        ScanRequestModel(
            location="path/to/file.exe",
            metainfo="file.exe",
            requested_action={
                "type": "movetag",
                "destination": {"path": "tenant-quarantine"},
                "tags": {"Verdict": "Malicious", "Source": "2g"},
            },
        )
    )

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert calls == [
        ("move", "bucket-gcs", "path/to/file.exe", "bucket-gcs", "tenant-quarantine/path/to/file.exe"),
        ("tag", "bucket-gcs", "tenant-quarantine/path/to/file.exe", {"Verdict": "Malicious", "Source": "2g"}),
    ]


@pytest.mark.asyncio
async def test_item_action_handler_uses_requested_tag_without_global_config(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.asset_bucket = "bucket-gcs"
    gc.config.item_action = ItemActionEnum.DELETE

    calls: list[tuple] = []

    monkeypatch.setattr(gc.gcs_client, "key_exists", lambda bucket, key: True)
    monkeypatch.setattr(
        gc.gcs_client,
        "tag_object",
        lambda bucket, key, tags=None: calls.append(("tag", bucket, key, tags)) or True,
    )

    resp = await gc.item_action_handler(
        ScanRequestModel(
            location="path/to/file.exe",
            metainfo="file.exe",
            requested_action={
                "type": "tag",
                "tags": {"Classification": "Malicious"},
            },
        )
    )

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.TAG
    assert calls == [
        ("tag", "bucket-gcs", "path/to/file.exe", {"Classification": "Malicious"}),
    ]
