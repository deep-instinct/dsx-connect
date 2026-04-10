import os
from pydantic import Field, AliasChoices, SecretStr
from pathlib import Path

from connectors.framework.base_config import BaseConnectorConfig
from shared.dev_env import load_devenv


class M365MailConnectorConfig(BaseConnectorConfig):
    name: str = 'm365-mail-connector'

    # Graph auth (client credentials)
    tenant_id: str | None = Field(default=None,
                                  validation_alias=AliasChoices("M365_TENANT_ID", "DSXCONNECTOR_M365_TENANT_ID"),
                                  description="Azure AD tenant ID")
    client_id: str | None = Field(default=None,
                                  validation_alias=AliasChoices("M365_CLIENT_ID", "DSXCONNECTOR_M365_CLIENT_ID"),
                                  description="App registration (client ID)")
    client_secret: SecretStr | None = Field(default=None,
                                      validation_alias=AliasChoices("M365_CLIENT_SECRET", "DSXCONNECTOR_M365_CLIENT_SECRET"),
                                      description="Client secret (do not persist)")
    authority: str = Field(default="https://login.microsoftonline.com", description="OAuth authority")

    # Scope of mailboxes (initial, explicit list or comma‑separated)
    mailbox_upns: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "M365_MAILBOX_UPNS",
            "DSXCONNECTOR_M365_MAILBOX_UPNS",
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
    client_state: SecretStr | None = Field(default=None,
                                     validation_alias=AliasChoices("M365_CLIENT_STATE", "DSXCONNECTOR_M365_CLIENT_STATE"),
                                     description="Optional clientState to verify on webhook deliveries")
    delta_run_interval_seconds: int = Field(default=600, description="Interval for delta query backfill (seconds)")
    backfill_days: int = Field(
        default=0,
        validation_alias=AliasChoices("M365_BACKFILL_DAYS", "DSXCONNECTOR_M365_BACKFILL_DAYS"),
        description="If > 0, full scan backfills inbox messages with attachments from the last N days",
    )
    webhook_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "M365_WEBHOOK_URL",
            "DSXCONNECTOR_M365_WEBHOOK_URL",
            "DSXCONNECTOR_WEBHOOK_URL",
        ),
        description="Optional public HTTPS base URL for Graph webhooks (defaults to connector_url)",
    )
    trigger_delta_on_notification: bool = Field(
        default=False,
        description="Run delta immediately after receiving a webhook notification",
        validation_alias=AliasChoices(
            "M365_TRIGGER_DELTA_ON_NOTIFICATION",
            "DSXCONNECTOR_M365_TRIGGER_DELTA_ON_NOTIFICATION",
            "DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION",
        ),
    )
    # Action customization
    action_move_folder: str | None = Field(default=None, description="Folder display name to move malicious messages (e.g., 'Quarantine')")
    subject_tag_prefix: str | None = Field(default=None, description="Prefix to prepend to subject on malicious (e.g., '[Malicious] ') ")
    banner_html: str | None = Field(default=None, description="Optional HTML banner to prepend when stripping attachments")

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

class ConfigManager:
    _config: M365MailConnectorConfig | None = None

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
            if not (key.startswith("DSXCONNECTOR_") or key.startswith("M365_")):
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
        return True, str(env_file)

    @classmethod
    def get_config(cls) -> M365MailConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name(".dev.env"))
            cls._config = M365MailConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> M365MailConnectorConfig:
        load_devenv(Path(__file__).with_name(".dev.env"))
        cls._config = M365MailConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
