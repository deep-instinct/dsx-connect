from pydantic import Field, HttpUrl

from typing import Optional

from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum
from pathlib import Path
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
    connector_url: HttpUrl = Field(default="http://0.0.0.0:8590",
                                   description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    dsx_connect_url: HttpUrl = Field(default="http://0.0.0.0:8586/",
                                     description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")
    item_action: ItemActionEnum = ItemActionEnum.MOVE
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # Host path to scan; this should be the bind-mount source. The container always operates on asset_mount.
    asset: str = Field("/path/to/local/folder",
                       title="Scan folder (host path)",
                       description="Host/NAS directory to scan (bind-mounted into the container)")
    asset_mount: str = Field("/app/scan_folder", description="In-container path where the asset is mounted")
    filter: str = ""
    scan_by_path: bool = False

    ## Config settings specific to this Connector
    asset_display_name: str = "" # filessytem connector poses an issue for frontend since
    # the asset is actually map to folder on the connector's running container/pod, which is mapped to a folder on the host.
    # what we ant to display on the frontend, is the host folder, not the app/scan_folder.
    monitor: bool = False # if true, Connector will monitor location for new or modified files.
    monitor_force_polling: bool = False  # if true, force polling (useful on SMB/CIFS where inotify is unreliable)
    monitor_poll_interval_ms: int = 1000  # polling interval when force polling is enabled

    # Quarantine handling
    quarantine_mount: str = Field("/app/quarantine", description="In-container path for quarantine/move destinations")
    quarantine_host: Optional[str] = Field(default=None, description="Resolved host path for quarantine (derived from DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO)")

    # @field_validator("filter")
    # @classmethod
    # def validate_filter(cls, v: str) -> str:
    #     # cheap sanity (e.g., no unbalanced quotes, etc.)
    #     # or even call _tokenize_filter(v) here to ensure it parses
    #     try:
    #         _tokenize_filter(v)
    #         return v
    #     except Exception as e:
    #         # log a warning and return empty (scan all)
    #         dsx_logging.warning(f"Ignoring malformed filter '{v}': {e}")
    #         return ""

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"


# Singleton with reload capability
class ConfigManager:
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

        return cfg

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
