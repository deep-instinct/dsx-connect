import os
from pathlib import Path

from pydantic import HttpUrl, Field

from connectors.framework.base_config import BaseConnectorConfig
from shared.models.connector_models import ItemActionEnum
from shared.dev_env import load_devenv


class AWSS3ConnectorConfig(BaseConnectorConfig):
    """
    Configuration for connector.
    """

    name: str = 'aws-s3-connector'
    connector_url: HttpUrl = Field(
        default="http://0.0.0.0:8600",
        description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point",
    )
    dsx_connect_url: HttpUrl = Field(
        default="http://0.0.0.0:8586",
        description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point",
    )
    item_action: ItemActionEnum = ItemActionEnum.MOVE
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    # May be either "bucket" or "bucket/prefix"
    asset: str = "lg-test-02"
    filter: str = ""

    # Derived at startup from `asset`
    asset_bucket: str | None = None
    asset_prefix_root: str = ""

    # Connector-specific configuration
    s3_endpoint_url: str | None = None
    s3_endpoint_verify: bool = True

    # Persist UI-driven config updates only for local runtimes by default.
    config_persist_local_only: bool = Field(
        default=True,
        description="Persist runtime config updates only when DSXCONNECTOR_ENV_FILE is under ~/.dsx-connect-local",
    )

    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"


class ConfigManager:
    _config: AWSS3ConnectorConfig = None

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
        cfg = cls.get_config()
        if not getattr(cfg, "config_persist_local_only", True):
            return False, "disabled_by_config"

        env_file = cls._effective_env_file()
        if env_file is None:
            return False, "no_env_file"
        if not cls._is_local_env_file(env_file):
            return False, "env_not_local"
        if not env_file.exists():
            return False, "env_file_missing"

        allowed_exact = {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_DEFAULT_REGION",
        }
        cleaned: dict[str, str] = {}
        for k, v in (updates or {}).items():
            key = str(k or "").strip()
            if not (key.startswith("DSXCONNECTOR_") or key in allowed_exact):
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

    @classmethod
    def get_config(cls) -> AWSS3ConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = AWSS3ConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> AWSS3ConnectorConfig:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = AWSS3ConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
