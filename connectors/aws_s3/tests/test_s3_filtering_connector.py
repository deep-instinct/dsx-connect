import pytest

boto3 = pytest.importorskip("boto3")

from shared.models.connector_models import ScanRequestModel


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
