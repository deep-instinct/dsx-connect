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
