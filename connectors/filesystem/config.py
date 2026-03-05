from pathlib import Path
import os
from typing import Optional

from pydantic import Field, HttpUrl

from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum
from shared.dev_env import load_devenv
# from dsx_connect.utils.file_ops import _tokenize_filter


class FilesystemConnectorConfig(BaseConnectorConfig):
    """
    Configuration for connector.  Note that configuration is a pydantic base setting class, so we get the benefits of
    type checking, as well as code completion in an IDE.  pydantic settings also allows for overriding these default
    settings via environment variables or a .env file.

    If you wish to add a prefix to the environment variable overrides, change the value of env_prefix below.

    Example:
        env_prefix = "DSXCONNECTOR_"
        ...
        export DSXCONNECTOR_LOCATION = 'some path'

    You can also read in an optional .env file, which will be ignored is not available
    """
    name: str = 'filesystem-connector'
    connector_url: HttpUrl = Field(
        default="http://0.0.0.0:8590",
        description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point",
    )
    dsx_connect_url: HttpUrl = Field(
        default="http://0.0.0.0:8586/",
        description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point",
    )
    item_action: ItemActionEnum = ItemActionEnum.MOVE
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # Host path to scan; this should be the bind-mount source. The container always operates on asset_mount.
    asset: str = Field(
        "/path/to/local/folder",
        title="Scan folder (host path)",
        description="Host/NAS directory to scan (bind-mounted into the container)",
    )
    asset_mount: str = Field("/app/scan_folder", description="In-container path where the asset is mounted")
    filter: str = ""
    scan_by_path: bool = False

    # Config settings specific to this connector
    asset_display_name: str = ""
    monitor: bool = False
    monitor_force_polling: bool = False
    monitor_poll_interval_ms: int = 1000

    # Quarantine handling
    quarantine_mount: str = Field("/app/quarantine", description="In-container path for quarantine/move destinations")
    quarantine_host: Optional[str] = Field(
        default=None,
        description="Resolved host path for quarantine (derived from DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO)",
    )

    # Persist UI-driven config updates only for local runtimes by default.
    config_persist_local_only: bool = Field(
        default=True,
        description="Persist runtime config updates only when DSXCONNECTOR_ENV_FILE is under ~/.dsx-connect-local",
    )

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"


class ConfigManager:
    """Singleton with reload capability."""

    _config: FilesystemConnectorConfig = None

    @classmethod
    def _normalize_config(cls, cfg: FilesystemConnectorConfig) -> FilesystemConnectorConfig:
        """
        Align host paths with in-container mount paths so the connector always scans asset_mount
        while allowing DSXCONNECTOR_ASSET to be the host path (consistent with other connectors).
        """
        asset_host_raw = cfg.asset
        asset_host_path = Path(asset_host_raw).expanduser()

        asset_mount_raw = cfg.asset_mount or "/app/scan_folder"
        asset_mount_path = Path(asset_mount_raw).expanduser()

        # If running locally (no bind mount), fall back to the host path so scans still work in dev.
        if asset_mount_path == Path("/app/scan_folder") and not asset_mount_path.exists() and asset_host_path.exists():
            asset_mount_path = asset_host_path

        asset_host_str = str(asset_host_path)
        asset_mount_str = str(asset_mount_path)

        cfg.asset = asset_mount_str
        if not cfg.asset_display_name:
            cfg.asset_display_name = asset_host_str

        # Quarantine/move mapping:
        # - Treat DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO as a host path by default (for Docker bind mounts).
        # - Map to the in-container quarantine_mount when that path exists (container run) otherwise
        #   fall back to the host path (local dev without binds).
        quarantine_mount = Path(cfg.quarantine_mount or "/app/quarantine").expanduser()
        move_meta_raw = cfg.item_action_move_metainfo
        quarantine_host = None

        if move_meta_raw:
            move_meta_path = Path(move_meta_raw).expanduser()
            # If the provided path is already the in-container path, leave it.
            if move_meta_path == quarantine_mount:
                cfg.item_action_move_metainfo = str(quarantine_mount)
            else:
                quarantine_host = move_meta_path
        else:
            # default to a quarantine folder adjacent to the asset on host
            quarantine_host = Path(asset_host_path / "dsxconnect-quarantine")

        if quarantine_host:
            quarantine_host_str = str(quarantine_host)
            # prefer in-container path when it exists (i.e., when running with a bind mount)
            if quarantine_mount.exists():
                cfg.item_action_move_metainfo = str(quarantine_mount)
            else:
                cfg.item_action_move_metainfo = quarantine_host_str
            cfg.quarantine_host = quarantine_host_str

        return cfg

    @classmethod
    def _effective_env_file(cls) -> Path | None:
        path_str = os.getenv("DSXCONNECTOR_ENV_FILE")
        if not path_str:
            return None
        try:
            return Path(path_str).expanduser().resolve()
        except Exception:
            try:
                return Path(path_str).expanduser()
            except Exception:
                return None

    @classmethod
    def _is_local_env_file(cls, env_file: Path) -> bool:
        try:
            local_root = (Path.home() / ".dsx-connect-local").resolve()
            env_resolved = env_file.resolve()
            return env_resolved == local_root or local_root in env_resolved.parents
        except Exception:
            return False

    @classmethod
    def persist_runtime_overrides(cls, updates: dict[str, str]) -> tuple[bool, str]:
        cfg = cls.get_config()
        if not getattr(cfg, "config_persist_local_only", True):
            return False, "disabled_by_config"

        env_file = cls._effective_env_file()
        if env_file is None:
            return False, "no_env_file"
        if not cls._is_local_env_file(env_file):
            return False, "env_not_local"
        if not env_file.exists():
            return False, "env_file_missing"

        cleaned: dict[str, str] = {}
        for k, v in (updates or {}).items():
            key = str(k or "").strip()
            if not key.startswith("DSXCONNECTOR_"):
                continue
            val = str(v if v is not None else "")
            if "\n" in val or "\r" in val:
                val = val.replace("\r", " ").replace("\n", " ")
            cleaned[key] = val

        if not cleaned:
            return False, "no_supported_updates"

        lines = env_file.read_text(encoding="utf-8").splitlines()
        seen = set()
        out: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                out.append(line)
                continue
            key, _sep, _rest = line.partition("=")
            k = key.strip()
            if k in cleaned:
                out.append(f"{k}={cleaned[k]}")
                seen.add(k)
            else:
                out.append(line)

        for k, v in cleaned.items():
            if k not in seen:
                out.append(f"{k}={v}")

        env_file.write_text("\n".join(out) + "\n", encoding="utf-8")

        # Keep process env aligned for subsequent reloads in this process.
        for k, v in cleaned.items():
            os.environ[k] = v

        return True, str(env_file)

    @classmethod
    def get_config(cls) -> FilesystemConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = cls._normalize_config(FilesystemConnectorConfig())
        return cls._config

    @classmethod
    def reload_config(cls) -> FilesystemConnectorConfig:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = cls._normalize_config(FilesystemConnectorConfig())
        return cls._config


config = ConfigManager.get_config()
