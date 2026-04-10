import os
from pathlib import Path
from typing import Optional

from pydantic import Field, HttpUrl, AliasChoices, SecretStr

from connectors.framework.base_config import BaseConnectorConfig
from shared.dev_env import load_devenv


class OneDriveConnectorConfig(BaseConnectorConfig):
    name: str = "onedrive-connector"

    connector_url: HttpUrl = Field(
        default="http://localhost:8660",
        description="Base URL the connector listens on",
    )
    dsx_connect_url: HttpUrl = Field(
        default="http://localhost:8586",
        description="dsx-connect API URL",
    )

    item_action_move_metainfo: str = "dsxconnect-quarantine"

    asset: str = Field(
        default="",
        description="OneDrive folder path this connector is responsible for (e.g., /Documents/dsx-connect)",
    )

    filter: str = Field(
        default="",
        description="Optional rsync-style filter relative to the asset path",
    )

    scan_concurrency: int = Field(
        default=10,
        description="Max concurrent scan requests during full scan",
    )

    resolved_asset_base: Optional[str] = None

    tenant_id: str = Field(
        default="",
        description="Azure AD tenant ID",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_TENANT_ID",
            "ONEDRIVE_TENANT_ID",
            "OD_TENANT_ID",
        ),
    )
    client_id: str = Field(
        default="",
        description="Azure AD app (client) ID",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_CLIENT_ID",
            "ONEDRIVE_CLIENT_ID",
            "OD_CLIENT_ID",
        ),
    )
    client_secret: SecretStr = Field(
        default=SecretStr(""),
        description="Azure AD app client secret",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_CLIENT_SECRET",
            "ONEDRIVE_CLIENT_SECRET",
            "OD_CLIENT_SECRET",
        ),
    )
    user_id: str = Field(
        default="",
        description="User principal name (UPN) or user ID whose OneDrive will be scanned",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_USER_ID",
            "ONEDRIVE_USER_ID",
            "OD_USER_ID",
        ),
    )

    verify_tls: bool = Field(
        default=True,
        description="Verify TLS when calling dsx-connect",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_VERIFY_TLS",
            "ONEDRIVE_VERIFY_TLS",
            "OD_VERIFY_TLS",
        ),
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        description="Optional CA bundle when verify_tls is true",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_CA_BUNDLE",
            "ONEDRIVE_CA_BUNDLE",
            "OD_CA_BUNDLE",
        ),
    )

    webhook_enabled: bool = Field(
        default=False,
        description="Enable Microsoft Graph change notifications",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_ENABLED",
            "ONEDRIVE_WEBHOOK_ENABLED",
            "OD_WEBHOOK_ENABLED",
        ),
    )
    webhook_change_types: str = Field(
        default="updated",
        description="Comma-separated Graph change types (default: updated)",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_CHANGE_TYPES",
            "ONEDRIVE_WEBHOOK_CHANGE_TYPES",
            "OD_WEBHOOK_CHANGE_TYPES",
        ),
    )
    webhook_expire_minutes: int = Field(
        default=60,
        description="Subscription expiration window in minutes",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_EXPIRE_MINUTES",
            "ONEDRIVE_WEBHOOK_EXPIRE_MINUTES",
            "OD_WEBHOOK_EXPIRE_MINUTES",
        ),
    )
    webhook_refresh_seconds: int = Field(
        default=900,
        description="How often to reconcile the subscription",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_REFRESH_SECONDS",
            "ONEDRIVE_WEBHOOK_REFRESH_SECONDS",
            "OD_WEBHOOK_REFRESH_SECONDS",
        ),
    )
    webhook_client_state: Optional[SecretStr] = Field(
        default=None,
        description="Optional shared secret for webhook validation",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_CLIENT_STATE",
            "ONEDRIVE_WEBHOOK_CLIENT_STATE",
            "OD_WEBHOOK_CLIENT_STATE",
        ),
    )
    webhook_base_url: Optional[str] = Field(
        default=None,
        description="Public HTTPS base URL Graph should call (defaults to connector_url)",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_ONEDRIVE_WEBHOOK_URL",
            "ONEDRIVE_WEBHOOK_URL",
            "OD_WEBHOOK_URL",
            "DSXCONNECTOR_WEBHOOK_URL",
        ),
    )

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"

class ConfigManager:
    _config: OneDriveConnectorConfig | None = None

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
            if not (key.startswith("DSXCONNECTOR_") or key.startswith("ONEDRIVE_") or key.startswith("OD_")):
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
    def get_config(cls) -> OneDriveConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name(".dev.env"))
            cls._config = OneDriveConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> OneDriveConnectorConfig:
        load_devenv(Path(__file__).with_name(".dev.env"))
        cls._config = OneDriveConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
