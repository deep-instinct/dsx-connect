from pathlib import Path
from pydantic import HttpUrl, Field
from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum
from shared.dev_env import load_devenv

class {{ cookiecutter.__package_config_class_name }}(BaseConnectorConfig):
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
    name: str = '{{ cookiecutter.__release_name }}'
    connector_url: HttpUrl = Field(default="http://localhost:{{ cookiecutter.connector_port }}",
                                   description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    dsx_connect_url: HttpUrl = Field(default="{{ cookiecutter.__dsx_connect_url }}",
                                     description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsx-connect entry point")
    item_action: ItemActionEnum = ItemActionEnum.NOTHING # action to take on files - NOTHING, DELETE, MOVE, TAG, MOVE_TAG
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # Optional, human-friendly name shown on the dsx-connect UI card
    display_name: str = ""

    # define the asset this connector can perform full scan on... may also be used to filter on access scanning (webhook events)
    asset: str = ""
    filter: str = ""
    recursive: bool = True # deprecated

    ### Connector specific configuration

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

# Singleton with reload capability
class ConfigManager:
    _config: {{ cookiecutter.__package_config_class_name }} = None

    @classmethod
    def get_config(cls) -> {{ cookiecutter.__package_config_class_name }}:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = {{ cookiecutter.__package_config_class_name }}()
        return cls._config

    @classmethod
    def reload_config(cls) -> {{ cookiecutter.__package_config_class_name }}:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = {{ cookiecutter.__package_config_class_name }}()
        return cls._config


config = ConfigManager.get_config()
