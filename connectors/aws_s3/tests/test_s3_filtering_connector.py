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
