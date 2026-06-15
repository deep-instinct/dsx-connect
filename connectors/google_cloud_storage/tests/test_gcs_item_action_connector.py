import asyncio
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.models.connector_models import ItemActionEnum, ScanRequestModel


def _install_google_api_core_stub() -> None:
    if "google.api_core.exceptions" in sys.modules:
        return
    google_mod = sys.modules.setdefault("google", types.ModuleType("google"))
    api_core_mod = sys.modules.setdefault("google.api_core", types.ModuleType("google.api_core"))
    exc_mod = types.ModuleType("google.api_core.exceptions")

    class NotFound(Exception):
        pass

    class GoogleAPIError(Exception):
        pass

    exc_mod.NotFound = NotFound
    exc_mod.GoogleAPIError = GoogleAPIError
    sys.modules["google.api_core.exceptions"] = exc_mod
    setattr(api_core_mod, "exceptions", exc_mod)
    setattr(google_mod, "api_core", api_core_mod)


def test_item_action_handler_uses_requested_movetag(monkeypatch):
    _install_google_api_core_stub()
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

    request = ScanRequestModel(
        location="path/to/file.exe",
        metainfo="file.exe",
        job_item_id="job_item_c23bbf85bc2145abb4a3499f66442431",
        requested_action={
            "type": "movetag",
            "destination": {"path": "tenant-quarantine", "filename": "file.exe_c23bbf85bc"},
            "tags": {"Verdict": "Malicious", "Source": "2g"},
        },
    )

    resp = asyncio.run(gc.item_action_handler(request))

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert calls == [
        ("move", "bucket-gcs", "path/to/file.exe", "bucket-gcs", "tenant-quarantine/path/to/file.exe_c23bbf85bc"),
        ("tag", "bucket-gcs", "tenant-quarantine/path/to/file.exe_c23bbf85bc", {"Verdict": "Malicious", "Source": "2g"}),
    ]


def test_item_action_handler_uses_requested_tag_without_global_config(monkeypatch):
    _install_google_api_core_stub()
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

    request = ScanRequestModel(
        location="path/to/file.exe",
        metainfo="file.exe",
        requested_action={
            "type": "tag",
            "tags": {"Classification": "Malicious"},
        },
    )

    resp = asyncio.run(gc.item_action_handler(request))

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.TAG
    assert calls == [
        ("tag", "bucket-gcs", "path/to/file.exe", {"Classification": "Malicious"}),
    ]


def test_item_action_handler_always_appends_suffix_at_end_for_quarantine(monkeypatch):
    _install_google_api_core_stub()
    import connectors.google_cloud_storage.google_cloud_storage_connector as gc

    gc.config.asset = "bucket-gcs"
    gc.config.asset_bucket = "bucket-gcs"
    gc.config.item_action = ItemActionEnum.NOTHING

    calls: list[tuple] = []
    existing = {"path/to/file.exe": True}

    monkeypatch.setattr(gc.gcs_client, "key_exists", lambda bucket, key: existing.get(key, False))
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
    request = ScanRequestModel(
        location="path/to/file.exe",
        metainfo="file.exe",
        job_item_id="job_item_41f3998044abcdef1234567890fedcba",
        requested_action={
            "type": "movetag",
            "destination": {"path": "tenant-quarantine", "filename": "file.exe_41f3998044"},
            "tags": {"Verdict": "Malicious", "Source": "2g"},
        },
    )

    resp = asyncio.run(gc.item_action_handler(request))

    assert resp.status.value == "success"
    assert resp.item_action == ItemActionEnum.MOVE_TAG
    assert calls == [
        ("move", "bucket-gcs", "path/to/file.exe", "bucket-gcs", "tenant-quarantine/path/to/file.exe_41f3998044"),
        ("tag", "bucket-gcs", "tenant-quarantine/path/to/file.exe_41f3998044", {"Verdict": "Malicious", "Source": "2g"}),
    ]
