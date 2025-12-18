from typing import Optional

from pydantic import HttpUrl, Field, AliasChoices
from pydantic_settings import BaseSettings
from shared.models.connector_models import ItemActionEnum
from connectors.framework.base_config import BaseConnectorConfig
from pathlib import Path
from shared.dev_env import load_devenv

class SharepointConnectorConfig(BaseConnectorConfig):
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
    name: str = 'sharepoint-connector'
    connector_url: HttpUrl = Field(default="http://localhost:8620",
                                   description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    dsx_connect_url: HttpUrl = Field(default="http://localhost:8586",
                                     description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")
    item_action: ItemActionEnum = ItemActionEnum.NOTHING # action to take on files - NOTHING, DELETE, MOVE, TAG, MOVE_TAG
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # define the asset this connector can perform full scan on... may also be used to filter on access scanning (webhook events)
    asset: str = ""
    filter: str = ""
    # Concurrency for enqueueing scan requests during full scan
    scan_concurrency: int = Field(default=10, description="Max concurrent scan_file_request enqueues during full scan")
    # Internal: resolved base path within the drive (derived at startup from asset/filter/URL)
    resolved_asset_base: Optional[str] = None

    # SharePoint / Graph settings (client-credentials)
    sp_tenant_id: str = Field(default="", description="Azure AD Tenant ID")
    sp_client_id: str = Field(default="", description="Azure AD App (client) ID")
    sp_client_secret: str = Field(default="", description="Azure AD App client secret")
    sp_hostname: str = Field(default="", description="SharePoint hostname, e.g., contoso.sharepoint.com")
    sp_site_path: str = Field(default="", description="SharePoint site path, e.g., MySiteOrCollection")
    sp_drive_name: Optional[str] = Field(default=None, description="Optional drive name; default drive if omitted")

    # TLS toggles for outbound Graph requests
    sp_use_tls: bool = Field(default=True, description="Use HTTPS for Graph (always true for graph.microsoft.com)")
    sp_verify_tls: bool = Field(default=True, description="Verify TLS certificates for outbound requests")
    sp_ca_bundle: Optional[str] = Field(default=None, description="Optional CA bundle path for certificate verification")
    sp_log_token_claims: bool = Field(default=False, description="Log decoded OAuth token claims once (no raw token)")

    # Performance tuning
    sp_graph_page_size: int = Field(default=200, description="Preferred Graph page size (odata.maxpagesize)")
    sp_use_delta_for_scan: bool = Field(default=False, description="Use Graph drive delta for full-scan enumeration")
    sp_provider_mode: str = Field(default="graph", description="Provider mode: graph | spo_rest | mixed")
    sp_rest_row_limit: int = Field(default=5000, description="Row limit for REST RenderListDataAsStream")
    sp_list_id: Optional[str] = Field(default=None, description="List GUID for REST mode (e.g., a large custom list or Documents list)")
    sp_digest_ttl_s: int = Field(default=1500, description="Cache TTL for SharePoint request digests")

    # Webhook (change notification) settings
    sp_webhook_enabled: bool = Field(
        default=False,
        description="Enable Microsoft Graph change notifications to auto-trigger scans for new/updated files",
        validation_alias=AliasChoices("DSXCONNECTOR_SP_WEBHOOK_ENABLED", "SP_WEBHOOK_ENABLED", "WEBHOOK_ENABLED"),
    )
    sp_webhook_change_types: str = Field(
        default="updated",
        description="Comma-separated Graph change types to subscribe to (e.g., 'created,updated')",
        validation_alias=AliasChoices("DSXCONNECTOR_SP_WEBHOOK_CHANGE_TYPES", "SP_WEBHOOK_CHANGE_TYPES", "WEBHOOK_CHANGE_TYPES"),
    )
    sp_webhook_expire_minutes: int = Field(
        default=60,
        description="Subscription expiration window in minutes (Graph max varies by resource; renew happens automatically)",
        validation_alias=AliasChoices("DSXCONNECTOR_SP_WEBHOOK_EXPIRE_MINUTES", "SP_WEBHOOK_EXPIRE_MINUTES", "WEBHOOK_EXPIRE_MINUTES"),
    )
    sp_webhook_refresh_seconds: int = Field(
        default=900,
        description="How often to reconcile/renew the Graph subscription (seconds)",
        validation_alias=AliasChoices("DSXCONNECTOR_SP_WEBHOOK_REFRESH_SECONDS", "SP_WEBHOOK_REFRESH_SECONDS", "WEBHOOK_REFRESH_SECONDS"),
    )
    sp_webhook_client_state: Optional[str] = Field(
        default=None,
        description="Optional clientState to require on inbound notifications from Graph",
        validation_alias=AliasChoices("DSXCONNECTOR_SP_WEBHOOK_CLIENT_STATE", "SP_WEBHOOK_CLIENT_STATE", "WEBHOOK_CLIENT_STATE"),
    )
    webhook_base_url: Optional[str] = Field(
        default=None,
        description="Public HTTPS base URL Graph should call for webhook events (defaults to connector_url)",
        validation_alias=AliasChoices("SP_WEBHOOK_URL", "WEBHOOK_URL", "DSXCONNECTOR_WEBHOOK_URL"),
    )

    ### Connector specific configuration

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

# Singleton with reload capability
class ConfigManager:
    _config: SharepointConnectorConfig = None

    @classmethod
    def get_config(cls) -> SharepointConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = SharepointConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> SharepointConnectorConfig:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = SharepointConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
