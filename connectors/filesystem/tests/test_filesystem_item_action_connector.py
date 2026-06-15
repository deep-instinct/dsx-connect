import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.models.connector_models import ItemActionEnum, ScanRequestModel


def test_item_action_tag_writes_sidecar(tmp_path, monkeypatch):
    from connectors.filesystem import filesystem_connector as fsconn

    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(fsconn.config, "item_action", ItemActionEnum.NOTHING)

    request = ScanRequestModel(
        location=str(sample),
        metainfo=sample.name,
        requested_action={
            "type": "tag",
            "tags": {"Verdict": "Malicious", "Source": "2g"},
        },
    )

    resp = asyncio.run(fsconn.item_action_handler(request))

    sidecar = tmp_path / "sample.txt.dsx.tags.json"
    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.TAG
    assert sidecar.exists()
    assert '"Source": "2g"' in sidecar.read_text(encoding="utf-8")


def test_item_action_movetag_moves_and_writes_sidecar(tmp_path, monkeypatch):
    from connectors.filesystem import filesystem_connector as fsconn

    source_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    source_root.mkdir()
    quarantine_root.mkdir()
    sample = source_root / "sample.txt"
    sample.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(fsconn.config, "asset", str(source_root))
    monkeypatch.setattr(fsconn.config, "item_action", ItemActionEnum.NOTHING)

    request = ScanRequestModel(
        location=str(sample),
        metainfo=sample.name,
        job_item_id="job_item_c23bbf85bc2145abb4a3499f66442431",
        requested_action={
            "type": "movetag",
            "destination": {"path": str(quarantine_root), "filename": "sample.txt_c23bbf85bc"},
            "tags": {"Verdict": "Malicious"},
        },
    )

    resp = asyncio.run(fsconn.item_action_handler(request))

    moved = quarantine_root / "sample.txt_c23bbf85bc"
    sidecar = quarantine_root / "sample.txt_c23bbf85bc.dsx.tags.json"
    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert not sample.exists()
    assert moved.exists()
    assert sidecar.exists()
    assert '"Verdict": "Malicious"' in sidecar.read_text(encoding="utf-8")


def test_item_action_movetag_always_appends_suffix_at_end(tmp_path, monkeypatch):
    from connectors.filesystem import filesystem_connector as fsconn

    source_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    source_root.mkdir()
    quarantine_root.mkdir()
    sample = source_root / "sample.exe"
    sample.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(fsconn.config, "asset", str(source_root))
    monkeypatch.setattr(fsconn.config, "item_action", ItemActionEnum.NOTHING)

    request = ScanRequestModel(
        location=str(sample),
        metainfo=sample.name,
        job_item_id="job_item_41f3998044abcdef1234567890fedcba",
        requested_action={
            "type": "movetag",
            "destination": {"path": str(quarantine_root), "filename": "sample.exe_41f3998044"},
            "tags": {"Verdict": "Malicious"},
        },
    )

    resp = asyncio.run(fsconn.item_action_handler(request))

    moved = quarantine_root / "sample.exe_41f3998044"
    sidecar = quarantine_root / "sample.exe_41f3998044.dsx.tags.json"
    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert moved.exists()
    assert sidecar.exists()
