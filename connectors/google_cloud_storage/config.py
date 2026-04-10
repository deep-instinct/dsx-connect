import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, HttpUrl

from connectors.framework.base_config import BaseConnectorConfig
from shared.dev_env import load_devenv
from shared.models.connector_models import ItemActionEnum


class GoogleCloudStorageConnectorConfig(BaseConnectorConfig):
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
    name: str = 'google-cloud-storage-connector'
    connector_url: HttpUrl = Field(default="http://0.0.0.0:8595",
                                   # dsx-connect is running within dockers, and this connector is being run on the docker's host system
                                   description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    # connector_url: HttpUrl = Field(default="http://host.docker.internal:8595", # dsx-connect is running within dockers, and this connector is being run on the docker's host system
    #                                description="Base URL (http(s)://ip.add.ddr.ess|URL:port) of this connector entry point")
    dsx_connect_url: HttpUrl = Field(default="http://0.0.0.0:8586",
                                     description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")
    # dsx_connect_url: HttpUrl = Field(default="http://dsx-connect.127.0.0.1.nip.io:8080",
    #                                  description="Complete URL (http(s)://ip.add.ddr.ess|URL:port) of the dsxa entry point")

    item_action: ItemActionEnum = ItemActionEnum.TAG
    item_action_move_metainfo: str = "dsxconnect-quarantine"

    asset: str = "lg-test-01"
    filter: str = ""

    monitor: bool = False
    pubsub_project_id: str = Field(
        default="",
        description="GCP project that owns the Pub/Sub subscription used for bucket notifications.",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_PUBSUB_PROJECT_ID",
            "DSXCONNECTOR_GCS_PUBSUB_PROJECT_ID",
            "GCS_PUBSUB_PROJECT_ID",
            "PUBSUB_PROJECT_ID",
        ),
    )
    pubsub_subscription: str = Field(
        default="",
        description="Subscription name or full resource path that delivers bucket events.",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_PUBSUB_SUBSCRIPTION",
            "DSXCONNECTOR_GCS_PUBSUB_SUBSCRIPTION",
            "GCS_PUBSUB_SUBSCRIPTION",
            "PUBSUB_SUBSCRIPTION",
        ),
    )
    pubsub_endpoint: Optional[str] = Field(
        default=None,
        description="Optional override for the Pub/Sub API endpoint (used for emulators).",
        validation_alias=AliasChoices(
            "DSXCONNECTOR_PUBSUB_ENDPOINT",
            "DSXCONNECTOR_GCS_PUBSUB_ENDPOINT",
            "GCS_PUBSUB_ENDPOINT",
            "PUBSUB_ENDPOINT",
        ),
    )
    google_application_credentials: Optional[str] = Field(
        default=None,
        description="Optional path to a Google service account JSON credentials file.",
        validation_alias=AliasChoices(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "DSXCONNECTOR_GOOGLE_APPLICATION_CREDENTIALS",
            "DSXCONNECTOR_GCS_CREDENTIALS_FILE",
            "GCS_CREDENTIALS_FILE",
        ),
    )

    # Derived at startup from `asset`. For GCS, `asset` may be either
    #   - "bucket" or
    #   - "bucket/prefix"
    # We keep the raw `asset` for display and derive these for runtime use.
    asset_bucket: str | None = None
    asset_prefix_root: str = ""


    class Config:
        env_prefix = "DSXCONNECTOR_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "forbid"


# Singleton with reload capability
class ConfigManager:
    _config: GoogleCloudStorageConnectorConfig = None

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

        allowed_exact = {
            "GOOGLE_APPLICATION_CREDENTIALS",
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
        return True, str(env_file)

    @classmethod
    def get_config(cls) -> GoogleCloudStorageConnectorConfig:
        if cls._config is None:
            load_devenv(Path(__file__).with_name('.dev.env'))
            cls._config = GoogleCloudStorageConnectorConfig()
        return cls._config

    @classmethod
    def reload_config(cls) -> GoogleCloudStorageConnectorConfig:
        load_devenv(Path(__file__).with_name('.dev.env'))
        cls._config = GoogleCloudStorageConnectorConfig()
        return cls._config


config = ConfigManager.get_config()
