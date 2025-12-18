from pydantic import Field, AliasChoices
from pathlib import Path

from connectors.framework.base_config import BaseConnectorConfig
from shared.dev_env import load_devenv


class M365MailConnectorConfig(BaseConnectorConfig):
    name: str = 'm365-mail-connector'

    # Graph auth (client credentials)
    tenant_id: str | None = Field(default=None,
                                  validation_alias=AliasChoices("M365_TENANT_ID"),
                                  description="Azure AD tenant ID")
    client_id: str | None = Field(default=None,
                                  validation_alias=AliasChoices("M365_CLIENT_ID"),
                                  description="App registration (client ID)")
    client_secret: str | None = Field(default=None,
                                      validation_alias=AliasChoices("M365_CLIENT_SECRET"),
                                      description="Client secret (do not persist)")
    authority: str = Field(default="https://login.microsoftonline.com", description="OAuth authority")

    # Scope of mailboxes (initial, explicit list or comma‑separated)
    mailbox_upns: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "M365_MAILBOX_UPNS",
            "DSXCONNECTOR_ASSET",
            "ASSET",
        ),
        description="Comma-separated UPNs of target mailboxes",
    )

    # Processing policies
    max_attachment_bytes: int = Field(default=50 * 1024 * 1024, description="Max attachment size to process")
    handle_reference_attachments: bool = Field(default=False, description="Download and scan cloud attachments")
    enable_actions: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("DSXCONNECTOR_ENABLE_ACTIONS"),
        description="Legacy remediation toggle (deprecated; actions enable automatically when item_action != nothing)"
    )
    client_state: str | None = Field(default=None,
                                     validation_alias=AliasChoices("M365_CLIENT_STATE"),
                                     description="Optional clientState to verify on webhook deliveries")
    delta_run_interval_seconds: int = Field(default=600, description="Interval for delta query backfill (seconds)")
    webhook_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("M365_WEBHOOK_URL", "DSXCONNECTOR_WEBHOOK_URL"),
        description="Optional public HTTPS base URL for Graph webhooks (defaults to connector_url)",
    )
    trigger_delta_on_notification: bool = Field(
        default=False,
        description="Run delta immediately after receiving a webhook notification",
        validation_alias=AliasChoices("M365_TRIGGER_DELTA_ON_NOTIFICATION", "DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION"),
    )
    # Action customization
    action_move_folder: str | None = Field(default=None, description="Folder display name to move malicious messages (e.g., 'Quarantine')")
    subject_tag_prefix: str | None = Field(default=None, description="Prefix to prepend to subject on malicious (e.g., '[Malicious] ') ")
    banner_html: str | None = Field(default=None, description="Optional HTML banner to prepend when stripping attachments")

    class Config:
        env_prefix = "DSXCONNECTOR_"

load_devenv(Path(__file__).with_name(".dev.env"))


config = M365MailConnectorConfig()
