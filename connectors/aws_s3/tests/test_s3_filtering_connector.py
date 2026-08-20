import pytest

boto3 = pytest.importorskip("boto3")

from shared.models.connector_models import ScanRequestModel, ItemActionEnum


@pytest.mark.asyncio
async def test_full_scan_filters(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    # Prepare config
    s3c.config.asset = "bucket-a"
    s3c.config.filter = "**/*.txt"

    # Capture scan requests
    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req.location)

    monkeypatch.setattr(s3c.connector, "scan_file_request", fake_scan)

    # Patch client.keys to yield sample keys
    def fake_keys(bucket, base_prefix: str = "", filter_str: str = ""):
        yield {"Key": "keep.txt"}
        yield {"Key": "sub/keep2.txt"}
        yield {"Key": "drop.bin"}

    monkeypatch.setattr(s3c.aws_s3_client, "keys", fake_keys)

    resp = await s3c.full_scan_handler()
    assert resp.status.value == "success"
    assert calls == ["keep.txt", "sub/keep2.txt"]


@pytest.mark.asyncio
async def test_full_scan_batch_filters(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c
    from shared.models.status_responses import StatusResponse, StatusResponseEnum

    s3c.config.asset = "bucket-a"
    s3c.config.filter = "**/*.txt"

    batch_calls = []

    async def fake_scan_batch(reqs, batch_size=None):
        batch_calls.append(([r.location for r in reqs], batch_size))
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    async def fake_caps():
        return {"enabled": True, "default_size": 2, "max_size": 10}

    monkeypatch.setattr(s3c.connector, "scan_file_request_batch", fake_scan_batch)
    monkeypatch.setattr(s3c.connector, "get_core_scan_batch_capabilities", fake_caps)

    def fake_keys(bucket, base_prefix: str = "", filter_str: str = ""):
        yield {"Key": "keep.txt"}
        yield {"Key": "sub/keep2.txt"}
        yield {"Key": "drop.bin"}

    monkeypatch.setattr(s3c.aws_s3_client, "keys", fake_keys)

    resp = await s3c.full_scan_handler(batch=True, batch_size=2)
    assert resp.status.value == "success"
    assert batch_calls == [(["keep.txt", "sub/keep2.txt"], 2)]


@pytest.mark.asyncio
async def test_item_action_movetag_uses_requested_destination_filename(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    s3c.config.asset_bucket = "bucket-a"
    s3c.config.item_action = ItemActionEnum.NOTHING

    calls = []

    monkeypatch.setattr(s3c.aws_s3_client, "key_exists", lambda bucket, key: True)
    monkeypatch.setattr(
        s3c.aws_s3_client,
        "move_object",
        lambda src_bucket, src_key, dest_bucket, dest_key: calls.append(("move", src_bucket, src_key, dest_bucket, dest_key)) or True,
    )
    monkeypatch.setattr(
        s3c.aws_s3_client,
        "tag_object",
        lambda bucket, key, tags=None: calls.append(("tag", bucket, key, tags)) or True,
    )

    request = ScanRequestModel(
        location="scan/eicar.txt",
        metainfo="bucket-a/scan/eicar.txt",
        requested_action={
            "type": "movetag",
            "destination": {"path": "quarantine", "filename": "eicar.txt_c23bbf85bc"},
            "tags": {"Verdict": "Malicious"},
        },
    )

    resp = await s3c.item_action_handler(request)

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert calls == [
        ("move", "bucket-a", "scan/eicar.txt", "bucket-a", "quarantine/eicar.txt_c23bbf85bc"),
        ("tag", "bucket-a", "quarantine/eicar.txt_c23bbf85bc", {"Verdict": "Malicious"}),
    ]


@pytest.mark.asyncio
async def test_asset_discovery_reports_configured_bucket_prefix(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    s3c.config.asset = "bucket-a/inbound"
    s3c.config.asset_bucket = "bucket-a"
    s3c.config.asset_prefix_root = "inbound"

    response = await s3c.asset_discovery_handler(asset_type="bucket", source="configured_asset")

    assert response.status == "success"
    assert [asset.selector for asset in response.assets] == ["bucket-a/inbound"]
    assert response.assets[0].metadata == {
        "provider": "s3",
        "kind": "configured_bucket_prefix",
        "bucket": "bucket-a",
        "prefix": "inbound",
    }


@pytest.mark.asyncio
async def test_asset_discovery_all_combines_configured_bucket_and_inventory(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    s3c.config.asset = "bucket-a"
    s3c.config.asset_bucket = "bucket-a"
    s3c.config.asset_prefix_root = ""

    monkeypatch.setattr(s3c.aws_s3_client, "buckets", lambda: ["bucket-a", "bucket-b", "bucket-c"])

    response = await s3c.asset_discovery_handler(asset_type="bucket", source="all", limit=2)

    assert response.status == "success"
    assert response.source == "all"
    assert [asset.selector for asset in response.assets] == ["bucket-a", "bucket-b"]
    assert response.next_cursor == "2"


@pytest.mark.asyncio
async def test_asset_discovery_reports_unsupported_asset_type(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    response = await s3c.asset_discovery_handler(asset_type="folder", source="inventory_enumeration")

    assert response.status == "unsupported"
    assert response.unsupported is True
    assert response.message == "unsupported_asset_type:folder"


@pytest.mark.asyncio
async def test_object_listing_handler_uses_requested_bucket(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    s3c.config.asset = "bucket-default"
    s3c.config.asset_bucket = "bucket-default"
    s3c.config.asset_prefix_root = ""
    s3c.config.filter = ""

    calls = []

    def fake_list_object_page(bucket, *, base_prefix, filter_str, limit, cursor):
        calls.append((bucket, base_prefix, filter_str, limit, cursor))
        return (
            [
                {
                    "Key": "incoming/one.pdf",
                    "Size": 123,
                    "ETag": "etag-a",
                    "StorageClass": "STANDARD",
                }
            ],
            "cursor-b",
        )

    monkeypatch.setattr(s3c.aws_s3_client, "list_object_page", fake_list_object_page)

    response = await s3c.object_listing_handler(scope="bucket-requested/incoming", limit=10, cursor="cursor-a")

    assert response.status == "success"
    assert calls == [("bucket-requested", "incoming", "", 10, "cursor-a")]
    assert response.next_cursor == "cursor-b"
    assert [item.identity for item in response.objects] == ["bucket-requested/incoming/one.pdf"]
    assert response.objects[0].location == "incoming/one.pdf"
    assert response.objects[0].size_in_bytes == 123
    assert response.objects[0].metadata["provider"] == "s3"
    assert response.objects[0].metadata["bucket"] == "bucket-requested"


@pytest.mark.asyncio
async def test_read_file_handler_uses_metainfo_bucket(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    class FakeBody:
        def __init__(self, chunks):
            self._chunks = list(chunks)
            self.closed = False

        def read(self, _size):
            if not self._chunks:
                return b""
            return self._chunks.pop(0)

        def close(self):
            self.closed = True

    s3c.config.asset = "bucket-default"
    s3c.config.asset_bucket = "bucket-default"
    s3c.config.asset_prefix_root = ""

    calls = []
    body = FakeBody([b"abc"])

    def fake_get_object_stream(bucket, key):
        calls.append((bucket, key))
        return body, 3

    monkeypatch.setattr(s3c.aws_s3_client, "get_object_stream", fake_get_object_stream)

    response = await s3c.read_file_handler(
        ScanRequestModel(
            location="incoming/one.pdf",
            metainfo="bucket-requested/incoming/one.pdf",
        )
    )

    assert calls == [("bucket-requested", "incoming/one.pdf")]
    assert response.headers["content-length"] == "3"


@pytest.mark.asyncio
async def test_write_file_handler_uploads_to_requested_bucket(monkeypatch):
    import connectors.aws_s3.aws_s3_connector as s3c

    class FakeUpload:
        filename = "payload.txt"

        def __init__(self):
            self._chunks = [b"hello", b""]

        async def read(self, _size):
            return self._chunks.pop(0)

    calls = []

    def fake_upload_file(filepath, *, file_key, bucket):
        calls.append((bucket, file_key, filepath.read_bytes()))

    monkeypatch.setattr(s3c.aws_s3_client, "upload_file", fake_upload_file)

    response = await s3c.write_file_handler(
        bucket="bucket-requested",
        key="inbox/payload.txt",
        destination=None,
        file=FakeUpload(),
    )

    assert response == {
        "status": "success",
        "bucket": "bucket-requested",
        "key": "inbox/payload.txt",
        "uri": "s3://bucket-requested/inbox/payload.txt",
    }
    assert calls == [("bucket-requested", "inbox/payload.txt", b"hello")]
