import pytest
import sys
import types

pytest.importorskip("google.cloud.storage")

from shared.models.connector_models import ItemActionEnum, ScanRequestModel


def test_cloud_asset_inventory_helper_reads_first_page(monkeypatch):
    import google.cloud
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    class FakePage(list):
        next_page_token = "token-2"

    class FakePager:
        @property
        def pages(self):
            return iter(
                [
                    FakePage(
                        [
                            types.SimpleNamespace(
                                name="//storage.googleapis.com/projects/_/buckets/bucket-a",
                                asset_type="storage.googleapis.com/Bucket",
                                resource=types.SimpleNamespace(
                                    data={
                                        "name": "bucket-a",
                                        "location": "US",
                                        "storageClass": "STANDARD",
                                    }
                                ),
                            )
                        ]
                    )
                ]
            )

        def __iter__(self):
            raise AssertionError("helper should consume one page, not auto-iterate the full pager")

    class FakeAssetServiceClient:
        def list_assets(self, request):
            assert request["parent"] == "organizations/123"
            assert request["asset_types"] == ["storage.googleapis.com/Bucket"]
            assert request["content_type"] == "RESOURCE"
            assert request["page_size"] == 10
            return FakePager()

    fake_asset_v1 = types.SimpleNamespace(
        AssetServiceClient=FakeAssetServiceClient,
        ContentType=types.SimpleNamespace(RESOURCE="RESOURCE"),
    )
    monkeypatch.setitem(sys.modules, "google.cloud.asset_v1", fake_asset_v1)
    monkeypatch.setattr(google.cloud, "asset_v1", fake_asset_v1, raising=False)

    assets, next_cursor = gc._list_cloud_asset_inventory_buckets(scope="org:123", limit=10)

    assert [asset.selector for asset in assets] == ["bucket-a"]
    assert assets[0].metadata["discovery_source"] == "cloud_asset_inventory"
    assert assets[0].metadata["location"] == "US"
    assert next_cursor == "token-2"


def test_filtered_cloud_asset_inventory_walks_until_page_is_filled(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    calls = []

    def fake_cloud_asset_buckets(*, scope: str, limit: int, cursor: str | None = None):
        calls.append((limit, cursor))
        if cursor is None:
            return [
                gc.AssetDiscoveryItem(id="dev-a", display_name="dev-a", selector="dev-a"),
                gc.AssetDiscoveryItem(id="qa-a", display_name="qa-a", selector="qa-a"),
            ], "page-2"
        if cursor == "page-2":
            return [
                gc.AssetDiscoveryItem(id="prod-a", display_name="prod-a", selector="prod-a"),
                gc.AssetDiscoveryItem(id="prod-b", display_name="prod-b", selector="prod-b"),
            ], "page-3"
        return [
            gc.AssetDiscoveryItem(id="prod-c", display_name="prod-c", selector="prod-c"),
        ], None

    monkeypatch.setattr(gc, "_list_cloud_asset_inventory_buckets", fake_cloud_asset_buckets)

    assets, next_cursor = gc._list_filtered_cloud_asset_inventory_buckets(
        scope="org:123",
        limit=2,
        asset_filter_mode="begins_with",
        asset_filter_value="prod",
    )

    assert [asset.selector for asset in assets] == ["prod-a", "prod-b"]
    assert next_cursor == "page-3"
    assert calls == [(2, None), (2, "page-2")]


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
    monkeypatch.setattr(gc.config, "asset_inventory_scope", "")
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

    monkeypatch.setattr(gc.config, "asset_inventory_scope", "")
    monkeypatch.setattr(gc.gcs_client, "buckets", lambda: ["bucket-a", "bucket-b", "bucket-c"])

    resp = await gc.asset_discovery_handler(asset_type="bucket", source="inventory_enumeration", limit=2)

    assert resp.asset_type == "bucket"
    assert resp.source == "inventory_enumeration"
    assert resp.status == "success"
    assert [asset.selector for asset in resp.assets] == ["bucket-a", "bucket-b"]
    assert resp.next_cursor == "2"
    assert resp.assets[0].metadata["provider"] == "gcs"


@pytest.mark.asyncio
async def test_asset_discovery_uses_cloud_asset_inventory_when_scope_configured(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    def fake_cloud_asset_buckets(*, scope: str, limit: int, cursor: str | None = None):
        assert scope == "organizations/123"
        assert limit == 2
        assert cursor == "next-token"
        return (
            [
                gc.AssetDiscoveryItem(
                    id="bucket-a",
                    display_name="bucket-a",
                    selector="bucket-a",
                    metadata={
                        "provider": "gcs",
                        "bucket": "bucket-a",
                        "discovery_source": "cloud_asset_inventory",
                    },
                )
            ],
            "after-token",
        )

    monkeypatch.setattr(gc.config, "asset_inventory_scope", "organizations/123")
    monkeypatch.setattr(gc, "_list_cloud_asset_inventory_buckets", fake_cloud_asset_buckets)

    resp = await gc.asset_discovery_handler(
        asset_type="bucket",
        source="inventory_enumeration",
        limit=2,
        cursor="next-token",
    )

    assert resp.asset_type == "bucket"
    assert resp.source == "cloud_asset_inventory"
    assert resp.status == "success"
    assert [asset.selector for asset in resp.assets] == ["bucket-a"]
    assert resp.assets[0].metadata["discovery_source"] == "cloud_asset_inventory"
    assert resp.next_cursor == "after-token"


@pytest.mark.asyncio
async def test_asset_discovery_reports_cloud_asset_inventory_failure(monkeypatch):
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    def fail_cloud_asset_buckets(*, scope: str, limit: int, cursor: str | None = None):
        raise RuntimeError("403 cloudasset.assets.listResource permission denied")

    monkeypatch.setattr(gc.config, "asset_inventory_scope", "folders/456")
    monkeypatch.setattr(gc, "_list_cloud_asset_inventory_buckets", fail_cloud_asset_buckets)

    resp = await gc.asset_discovery_handler(asset_type="bucket", source="cloud_asset_inventory", limit=2)

    assert resp.unsupported is False
    assert resp.source == "cloud_asset_inventory"
    assert resp.status == "permission_denied"
    assert resp.assets == []
    assert resp.message == "asset_discovery_failed:403 cloudasset.assets.listResource permission denied"
    assert resp.required_permission == "cloudasset.assets.listResource"


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

    monkeypatch.setattr(gc.config, "asset_inventory_scope", "")

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
