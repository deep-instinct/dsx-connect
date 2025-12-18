from pathlib import Path
from typing import Optional

from pydantic import Field, HttpUrl, model_validator

from connectors.framework.base_config import BaseConnectorConfig
from shared.dev_env import load_devenv
from shared.models.connector_models import ItemActionEnum


class SalesforceConnectorConfig(BaseConnectorConfig):
    """
    Salesforce connector configuration driven by environment variables / .dev.env.
    """

    name: str = "salesforce-connector"
    connector_url: HttpUrl = Field(
        default="http://localhost:8670",
        description="Base URL (http(s)://host:port) of this connector entry point",
    )
    dsx_connect_url: HttpUrl = Field(
        default="http://127.0.0.1:8586",
        description="Complete URL (http(s)://host:port) of the dsx-connect entry point",
    )
    item_action: ItemActionEnum = ItemActionEnum.NOTHING
    item_action_move_metainfo: str = "dsxconnect-quarantine"
    display_name: str = ""

    # Asset/filter semantics are connector-specific. For Salesforce, treat `asset` as an additional SOQL filter clause.
    asset: str = Field(
        default="",
        description="Optional SOQL clause appended to the ContentVersion query (without WHERE). Example: \"ContentDocumentId = '069xx0000001234'\"",
    )
    filter: str = Field(
        default="",
        description="Optional comma-separated list of file extensions (e.g., \"pdf,docx\"). When set, only matching ContentVersions are queued.",
    )
    recursive: bool = True  # deprecated but kept for compatibility

    # Salesforce specific settings
    sf_login_url: HttpUrl = Field(
        default="https://login.salesforce.com",
        description="Salesforce OAuth base URL (set to https://test.salesforce.com for sandboxes).",
    )
    sf_api_version: str = Field(
        default="v60.0",
        description="Salesforce REST API version (e.g., v60.0).",
    )
    sf_client_id: str = Field(default="", description="Connected App consumer key.")
    sf_client_secret: str = Field(default="", description="Connected App consumer secret.")
    sf_username: str = Field(default="", description="Salesforce user name granted access to the Connected App.")
    sf_password: str = Field(default="", description="Salesforce user password.")
    sf_security_token: str = Field(
        default="",
        description="Optional Salesforce security token appended to the password for username-password OAuth flow.",
    )
    sf_where: str = Field(
        default="IsLatest = true",
        description="Base SOQL WHERE clause applied to ContentVersion (without the WHERE keyword).",
    )
    sf_fields: str = Field(
        default="Id, Title, FileExtension, ContentSize, ContentDocumentId, CreatedDate",
        description="Comma-separated ContentVersion fields to select.",
    )
    sf_order_by: str = Field(
        default="CreatedDate DESC",
        description="ORDER BY clause appended to the ContentVersion query (omit ORDER BY keyword to disable).",
    )
    sf_max_records: int = Field(
        default=500,
        ge=1,
        description="Maximum number of ContentVersion rows to queue for a single full scan (set to a larger value for full sweeps).",
    )
    sf_verify_tls: bool = Field(default=True, description="Verify Salesforce TLS certificates.")
    sf_ca_bundle: Optional[str] = Field(
        default=None,
        description="Optional CA bundle path when sf_verify_tls=true and using a custom CA.",
    )
    sf_http_timeout: float = Field(
        default=30.0,
        gt=0,
        description="HTTP timeout (seconds) for Salesforce API calls.",
    )

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

    @model_validator(mode="after")
    def normalize_api_version(self):
        if self.sf_api_version and not self.sf_api_version.lower().startswith("v"):
            self.sf_api_version = f"v{self.sf_api_version}"
        return self


class ConfigManager:
    """Singleton wrapper so handlers can reload configuration on demand."""

    _config: Optional[SalesforceConnectorConfig] = None

    @classmethod
    def get_config(cls) -> SalesforceConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name(".dev.env"))
            cls._config = SalesforceConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> SalesforceConnectorConfig:
        load_devenv(Path(__file__).with_name(".dev.env"))
        cls._config = SalesforceConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
