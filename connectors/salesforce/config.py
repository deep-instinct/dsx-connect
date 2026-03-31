import os
from pathlib import Path
from typing import Optional

from pydantic import Field, HttpUrl, model_validator, SecretStr

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
    sf_client_secret: SecretStr = Field(default=SecretStr(""), description="Connected App consumer secret.")
    sf_username: str = Field(default="", description="Salesforce user name granted access to the Connected App.")
    sf_password: SecretStr = Field(default=SecretStr(""), description="Salesforce user password.")
    sf_security_token: SecretStr = Field(
        default=SecretStr(""),
        description="Optional Salesforce security token appended to the password for username-password OAuth flow.",
    )
    sf_auth_method: str = Field(
        default="auto",
        description="Salesforce auth method: auto | jwt | password (auto prefers jwt when keys are present).",
    )
    sf_jwt_private_key: SecretStr = Field(
        default=SecretStr(""),
        description="PEM or base64-encoded private key for JWT Bearer flow.",
    )
    sf_jwt_private_key_file: Optional[str] = Field(
        default=None,
        description="Path to a PEM private key file for JWT Bearer flow.",
    )
    sf_jwt_algorithm: str = Field(
        default="RS256",
        description="JWT signing algorithm for the bearer assertion.",
    )
    sf_jwt_exp_seconds: int = Field(
        default=180,
        ge=60,
        le=600,
        description="JWT expiration window in seconds (default 3 minutes).",
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
        for k, v in cleaned.items():
            os.environ[k] = v

        return True, str(env_file)


config = ConfigManager.get_config()
