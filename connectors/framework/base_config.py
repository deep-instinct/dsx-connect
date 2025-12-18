from typing import Optional
from pydantic import HttpUrl, Field
from pydantic_settings import BaseSettings
from shared.models.connector_models import ItemActionEnum


class BaseConnectorConfig(BaseSettings):
    """
    Configuration for connector.  Note that configuration is a pydantic base setting class, so we get the benefits of
    type checking, as well as code completion in an IDE.  pydantic settings also allows for overriding these default
    settings via environment variables or a .env file.

    If you wish to add a prefix to the environment variable overrides, change the value of env_prefix below.

    Example:
        env_prefix = "DSXCONNECTOR_"
        ...
        export DSXCONNECTOR_LOCATION = 'some path'

    You can also read in an optional .env file, which will be ignored if not available
    """
    name: str = 'dsx-connector'
    connector_url: HttpUrl = Field(
        default="http://0.0.0.0:8588",
        description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point"
    )
    dsx_connect_url: HttpUrl = Field(
        default="http://0.0.0.0:8586",
        description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsx-connect entry point"
    )
    item_action: ItemActionEnum = ItemActionEnum.NOTHING
    item_action_move_metainfo: str = "dsxconnect-quarantine"
    asset: str = ""
    filter: str = ""
    # Optional, human-friendly name shown in UI cards
    display_name: str = ""
    # Optional, custom icon to show in UI; accepts data URI, raw SVG, or short emoji
    display_icon: str = ""

    # TLS/SSL settings (server + outbound)
    use_tls: bool = Field(default=False, description="Serve connector over HTTPS using provided cert/key")
    tls_certfile: Optional[str] = Field(default=None, description="Path to TLS certificate file")
    tls_keyfile: Optional[str] = Field(default=None, description="Path to TLS private key file")
    verify_tls: bool = Field(default=True, description="Verify TLS when making outbound HTTP calls")
    ca_bundle: Optional[str] = Field(default=None, description="Optional CA bundle path for outbound verification")

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"
