from __future__ import annotations

from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def test_reload_config_resolves_relative_credentials_against_env_file(monkeypatch, tmp_path: Path) -> None:
    _install_google_api_core_stub()
    import os
    from connectors.google_cloud_storage.config import ConfigManager

    env_file = tmp_path / ".env.local"
    env_file.write_text("GOOGLE_APPLICATION_CREDENTIALS=gcp-sa.json\n", encoding="utf-8")

    monkeypatch.setenv("DSXCONNECTOR_ENV_FILE", str(env_file))

    config = ConfigManager.reload_config()

    assert config.google_application_credentials == str((tmp_path / "gcp-sa.json").resolve())
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str((tmp_path / "gcp-sa.json").resolve())


def test_reload_config_reads_cloud_asset_inventory_scope(monkeypatch, tmp_path: Path) -> None:
    _install_google_api_core_stub()
    from connectors.google_cloud_storage.config import ConfigManager

    env_file = tmp_path / ".env.local"
    env_file.write_text("DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE=organizations/123456789\n", encoding="utf-8")

    monkeypatch.setenv("DSXCONNECTOR_ENV_FILE", str(env_file))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    config = ConfigManager.reload_config()

    assert config.asset_inventory_scope == "organizations/123456789"
