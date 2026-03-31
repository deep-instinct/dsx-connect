import pytest

import connectors.sharepoint.sharepoint_connector as spc
from shared.models.connector_models import ScanRequestModel, ItemActionEnum
from shared.models.status_responses import StatusResponse, StatusResponseEnum
from starlette.responses import StreamingResponse


@pytest.mark.asyncio
async def test_repo_check_success(monkeypatch):
    async def fake_test_connection():
        return True

    monkeypatch.setattr(spc.sp_client, "test_connection", fake_test_connection)
    resp = await spc.repo_check_handler()
    assert resp.status.value == "success"


@pytest.mark.asyncio
async def test_read_file_streams_content(monkeypatch):
    class DummyResp:
        async def aiter_bytes(self):
            yield b"chunk1"
            yield b"chunk2"

    async def fake_download(item_id):
        return DummyResp()

    monkeypatch.setattr(spc.sp_client, "download_file", fake_download)

    out = await spc.read_file_handler(ScanRequestModel(location="abc", metainfo="file.txt"))
    assert isinstance(out, StreamingResponse)


@pytest.mark.asyncio
async def test_item_action_delete_success(monkeypatch):
    # Force DELETE action
    orig_action = spc.config.item_action
    spc.config.item_action = ItemActionEnum.DELETE

    async def fake_delete(item_id: str):
        return None

    monkeypatch.setattr(spc.sp_client, "delete_file", fake_delete)
    try:
        resp = await spc.item_action_handler(ScanRequestModel(location="abc", metainfo="file.txt"))
        assert resp.status.value == "success"
        assert resp.item_action == ItemActionEnum.DELETE
    finally:
        spc.config.item_action = orig_action


@pytest.mark.asyncio
async def test_full_scan_enqueues(monkeypatch):
    # Provide a short list of files (no folders)
    async def fake_iter_files_recursive(path: str):
        yield {"id": "1", "name": "a.txt"}
        yield {"id": "2", "name": "b.txt"}

    calls = []

    async def fake_scan(req: ScanRequestModel):
        calls.append(req)
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(spc.sp_client, "iter_files_recursive", fake_iter_files_recursive)
    monkeypatch.setattr(spc.connector, "scan_file_request", fake_scan)

    resp = await spc.full_scan_handler()
    assert resp.status.value == "success"
    assert len(calls) == 2
    assert calls[0].location == "1"
    assert calls[1].location == "2"


@pytest.mark.asyncio
async def test_full_scan_enqueues_in_batches(monkeypatch):
    async def fake_iter_files_recursive(path: str):
        yield {"id": "1", "name": "a.txt"}
        yield {"id": "2", "name": "b.txt"}
        yield {"id": "3", "name": "c.txt"}

    calls = []

    async def fake_caps():
        return {"enabled": True, "default_size": 2, "max_size": 2}

    async def fake_scan_batch(requests, batch_size: int):
        calls.append((requests, batch_size))
        from shared.models.status_responses import StatusResponse, StatusResponseEnum
        return StatusResponse(status=StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(spc.sp_client, "iter_files_recursive", fake_iter_files_recursive)
    monkeypatch.setattr(spc.connector, "get_core_scan_batch_capabilities", fake_caps)
    monkeypatch.setattr(spc.connector, "scan_file_request_batch", fake_scan_batch)

    resp = await spc.full_scan_handler(batch=True, batch_size=2)
    assert resp.status.value == "success"
    assert len(calls) == 2
    assert [req.location for req in calls[0][0]] == ["1", "2"]
    assert [req.location for req in calls[1][0]] == ["3"]
    assert calls[0][1] == 2
