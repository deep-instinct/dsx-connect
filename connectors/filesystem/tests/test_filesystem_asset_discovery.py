import sys
from pathlib import Path

import pytest


@pytest.fixture()
def fsconn():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from connectors.filesystem import filesystem_connector

    return filesystem_connector


@pytest.mark.asyncio
async def test_configured_asset_discovery_returns_scan_root(tmp_path, monkeypatch, fsconn):
    monkeypatch.setattr(fsconn.config, "asset", str(tmp_path))
    monkeypatch.setattr(fsconn.config, "item_action_move_metainfo", str(tmp_path / "quarantine"))
    monkeypatch.setattr(fsconn.config, "quarantine_host", None)

    response = await fsconn.asset_discovery_handler(asset_type="folder", source="configured_asset")

    assert response.status == "success"
    assert response.asset_type == "folder"
    assert response.assets[0].selector == tmp_path.as_posix()
    assert response.assets[0].display_name == tmp_path.name
    assert response.assets[0].metadata["configured_root"] is True
    assert response.assets[0].metadata["relative_path"] == "."


@pytest.mark.asyncio
async def test_inventory_enumeration_returns_immediate_child_directories_only(tmp_path, monkeypatch, fsconn):
    (tmp_path / "finance").mkdir()
    (tmp_path / "finance" / "nested").mkdir()
    (tmp_path / "legal").mkdir()
    (tmp_path / "root-file.txt").write_text("not an asset")
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    monkeypatch.setattr(fsconn.config, "asset", str(tmp_path))
    monkeypatch.setattr(fsconn.config, "item_action_move_metainfo", str(quarantine))
    monkeypatch.setattr(fsconn.config, "quarantine_host", None)

    response = await fsconn.asset_discovery_handler(asset_type="folder", source="inventory_enumeration")

    assert response.status == "success"
    assert response.asset_type == "folder"
    assert [asset.display_name for asset in response.assets] == ["finance", "legal"]
    assert [asset.metadata["relative_path"] for asset in response.assets] == ["finance", "legal"]
    assert all(asset.metadata["kind"] == "directory" for asset in response.assets)


@pytest.mark.asyncio
async def test_inventory_enumeration_supports_limit_cursor_and_filter(tmp_path, monkeypatch, fsconn):
    for name in ["alpha", "beta", "gamma"]:
        (tmp_path / name).mkdir()
    monkeypatch.setattr(fsconn.config, "asset", str(tmp_path))
    monkeypatch.setattr(fsconn.config, "item_action_move_metainfo", str(tmp_path / "quarantine"))
    monkeypatch.setattr(fsconn.config, "quarantine_host", None)

    first = await fsconn.asset_discovery_handler(
        asset_type="folder",
        source="inventory_enumeration",
        limit=1,
        asset_filter_mode="contains",
        asset_filter_value="a",
    )
    second = await fsconn.asset_discovery_handler(
        asset_type="folder",
        source="inventory_enumeration",
        limit=2,
        cursor=first.next_cursor,
        asset_filter_mode="contains",
        asset_filter_value="a",
    )

    assert [asset.display_name for asset in first.assets] == ["alpha"]
    assert first.next_cursor == "1"
    assert [asset.display_name for asset in second.assets] == ["beta", "gamma"]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_bucket_asset_discovery_is_unsupported_for_filesystem(tmp_path, monkeypatch, fsconn):
    monkeypatch.setattr(fsconn.config, "asset", str(tmp_path))

    response = await fsconn.asset_discovery_handler(asset_type="bucket", source="inventory_enumeration")

    assert response.status == "unsupported"
    assert response.unsupported is True
    assert response.message == "filesystem_asset_type_unsupported"
