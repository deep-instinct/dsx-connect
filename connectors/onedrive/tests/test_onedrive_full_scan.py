import pytest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.models.connector_models import ItemActionEnum


@pytest.mark.asyncio
async def test_full_scan_batch_filters(monkeypatch):
    import connectors.onedrive.onedrive_connector as od

    od.config.resolved_asset_base = "base"
    od.config.filter = "sub1/*"

    async def fake_iter_files_recursive(base_path):
        assert base_path == "base"
        yield {"id": "1", "path": "base/sub1/a.txt"}
        yield {"id": "2", "path": "base/sub1/deep/b.txt"}
        yield {"id": "3", "path": "base/sub2/c.txt"}
        yield {"id": "4", "path": "base/sub1", "folder": {"childCount": 1}}

    batch_calls = []

    async def fake_scan_batch(reqs):
        batch_calls.append([(req.location, req.metainfo) for req in reqs])
        return od.StatusResponse(status=od.StatusResponseEnum.SUCCESS, message="ok")

    monkeypatch.setattr(od.client, "iter_files_recursive", fake_iter_files_recursive)
    monkeypatch.setattr(od.connector, "scan_file_request_batch", fake_scan_batch)

    resp = await od.full_scan_handler(batch=True, batch_size=100)
    assert resp.status.value == "success"
    assert batch_calls == [[("1", "base/sub1/a.txt")]]


@pytest.mark.asyncio
async def test_full_scan_counts_only_success(monkeypatch):
    import connectors.onedrive.onedrive_connector as od

    od.config.resolved_asset_base = "base"
    od.config.filter = ""
    od.config.scan_concurrency = 2

    async def fake_iter_files_recursive(base_path):
        yield {"id": "1", "path": "base/a.txt"}
        yield {"id": "2", "path": "base/b.txt"}

    calls = []

    async def fake_scan(req):
        calls.append(req.location)
        status = od.StatusResponseEnum.SUCCESS if req.location == "1" else od.StatusResponseEnum.ERROR
        return od.StatusResponse(status=status, message="ok")

    monkeypatch.setattr(od.client, "iter_files_recursive", fake_iter_files_recursive)
    monkeypatch.setattr(od.connector, "scan_file_request", fake_scan)

    resp = await od.full_scan_handler()
    assert resp.status.value == "success"
    assert "enqueued=1" in (resp.description or "")
    assert calls == ["1", "2"]


@pytest.mark.asyncio
async def test_item_action_move_tag_uses_requested_destination(monkeypatch):
    import connectors.onedrive.onedrive_connector as od

    orig_action = od.config.item_action
    orig_target = od.config.item_action_move_metainfo
    orig_base = od.config.resolved_asset_base
    od.config.item_action = ItemActionEnum.NOTHING
    od.config.item_action_move_metainfo = "fallback-target"
    od.config.resolved_asset_base = ""

    calls = []

    async def fake_move(item_id: str, dest_folder: str, new_name=None, conflict_behavior="rename"):
        calls.append((item_id, dest_folder, new_name, conflict_behavior))
        return {"id": item_id}

    monkeypatch.setattr(od.client, "move_file", fake_move)
    try:
        resp = await od.item_action_handler(
            od.ScanRequestModel(
                location="abc",
                metainfo="file.txt",
                requested_action={
                    "type": "movetag",
                    "destination": {"path": "tenant-quarantine", "filename": "file.txt_c23bbf85bc"},
                },
            )
        )
        assert resp.status.value == "success"
        assert resp.item_action == od.ItemActionEnum.MOVE_TAG
        assert "Tagging skipped" in resp.message
        assert calls == [("abc", "tenant-quarantine", "file.txt_c23bbf85bc", "rename")]
    finally:
        od.config.item_action = orig_action
        od.config.item_action_move_metainfo = orig_target
        od.config.resolved_asset_base = orig_base


@pytest.mark.asyncio
async def test_item_action_tag_requested_returns_not_supported():
    import connectors.onedrive.onedrive_connector as od

    orig_action = od.config.item_action
    od.config.item_action = ItemActionEnum.DELETE

    try:
        resp = await od.item_action_handler(
            od.ScanRequestModel(
                location="abc",
                metainfo="file.txt",
                requested_action={
                    "type": "tag",
                    "tags": {"Verdict": "Malicious"},
                },
            )
        )
        assert resp.status.value == "nothing"
        assert resp.item_action == od.ItemActionEnum.TAG
        assert "not supported" in resp.message
    finally:
        od.config.item_action = orig_action
