import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.models.connector_models import ItemActionEnum, ScanRequestModel


def test_item_action_move_tag_uses_requested_destination(monkeypatch):
    import connectors.sharepoint.sharepoint_connector as spc

    orig_action = spc.config.item_action
    orig_target = spc.config.item_action_move_metainfo
    orig_asset = spc.config.asset
    spc.config.item_action = ItemActionEnum.NOTHING
    spc.config.item_action_move_metainfo = "fallback-target"
    spc.config.asset = "root"

    calls = []

    async def fake_move(item_id: str, dest_folder: str, new_name=None, conflict_behavior="rename"):
        calls.append((item_id, dest_folder, new_name, conflict_behavior))
        return {"id": item_id}

    monkeypatch.setattr(spc.sp_client, "move_file", fake_move)
    try:
        request = ScanRequestModel(
            location="abc",
            metainfo="file.txt",
            requested_action={
                "type": "movetag",
                "destination": {"path": "tenant-quarantine", "filename": "file.txt_c23bbf85bc"},
            },
        )
        resp = asyncio.run(spc.item_action_handler(request))
        assert resp.status.value == "success"
        assert resp.item_action == ItemActionEnum.MOVE_TAG
        assert "Tagging skipped" in resp.message
        assert calls == [("abc", "root/tenant-quarantine", "file.txt_c23bbf85bc", "rename")]
    finally:
        spc.config.item_action = orig_action
        spc.config.item_action_move_metainfo = orig_target
        spc.config.asset = orig_asset


def test_item_action_tag_requested_returns_not_supported():
    import connectors.sharepoint.sharepoint_connector as spc

    orig_action = spc.config.item_action
    spc.config.item_action = ItemActionEnum.DELETE

    try:
        request = ScanRequestModel(
            location="abc",
            metainfo="file.txt",
            requested_action={
                "type": "tag",
                "tags": {"Verdict": "Malicious"},
            },
        )
        resp = asyncio.run(spc.item_action_handler(request))
        assert resp.status.value == "nothing"
        assert resp.item_action == ItemActionEnum.TAG
        assert "not supported" in resp.message
    finally:
        spc.config.item_action = orig_action
