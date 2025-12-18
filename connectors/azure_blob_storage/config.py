from pydantic import HttpUrl, Field

from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum
from pathlib import Path
from shared.dev_env import load_devenv


class AzureBlobStorageConnectorConfig(BaseConnectorConfig):
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
    name: str = 'azure-blob-storage-connector'
    connector_url: HttpUrl = Field(default="http://127.0.0.1:8610",
                                   description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    # connector_url: HttpUrl = Field(default="http://host.docker.internal:8610",
    #                                description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    dsx_connect_url: HttpUrl = Field(default="http://127.0.0.1:8586",
                                     description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")
    # dsx_connect_url: HttpUrl = Field(default="http://dsx-connect.127.0.0.1.nip.io:8080",
    #                                  description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")
    item_action: ItemActionEnum = ItemActionEnum.NOTHING
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # define the asset this connector can perform full scan on... may also be used to filter on access scanning (webhook events)
    asset: str = "lg-test-01"
    filter: str = ""

    # Derived at startup from `asset`. For Azure, `asset` may be either
    #   - "container" or
    #   - "container/prefix"
    # We keep the raw `asset` for display and derive these for runtime use.
    asset_container: str | None = None
    asset_prefix_root: str = ""

    # Performance tuning
    # Max concurrent scan_file_request enqueues during full scan
    scan_concurrency: int = Field(default=10, description="Max concurrent scan_file_request enqueues during full scan")
    # Optional page size hint for Azure list_blobs pagination
    list_page_size: int | None = Field(default=1000, description="Preferred Azure list_blobs page size (results_per_page)")

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"


# Singleton with reload capability
class ConfigManager:
    _config: AzureBlobStorageConnectorConfig = None

    @classmethod
    def get_config(cls) -> AzureBlobStorageConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = AzureBlobStorageConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> AzureBlobStorageConnectorConfig:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = AzureBlobStorageConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
