# dsx_connect/config.py
from enum import Enum
import os
from pathlib import Path
from typing import Final

from pydantic import AnyUrl, Field, AliasChoices, model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.dev_env import load_devenv


class AppEnv(str, Enum):
    dev = "dev"
    stg = "stg"
    prod = "prod"


class AuthConfig(BaseSettings):
    enabled: bool = False
    enrollment_token: str = "dev-enroll"

    jwt_secret: str = "dev-change-me"
    jwt_audience: str = "dsx-connect"
    jwt_issuer: str = "dsx-connect"
    jwt_ttl: int = 900  # 15m

    hmac_max_skew: int = 60

    class Config:
        env_prefix = "DSXCONNECT_AUTH__"
        case_sensitive = False


# Note: Storage backend is auto-detected from DSXCONNECT_RESULTS_DB; no enum required.


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    # Default location/URL. For Redis, this should be a redis:// URL (DB index typically 3)
    # Environment override: DSXCONNECT_RESULTS_DB (redis://... => Redis; anything else => in‑memory)
    loc: str = Field(
        default="redis://redis:6379/3",
        validation_alias=AliasChoices("DSXCONNECT_RESULTS_DB"),
    )
    retain: int = Field(
        default=1000,
        validation_alias=AliasChoices("DSXCONNECT_RESULTS_DB__RETAIN", "DSXCONNECT_DATABASE__RETAIN"),
    )


class ScannerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    scan_binary_url: str = "http://0.0.0.0:5000/scan/binary/v2"


class SyslogConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    syslog_server_url: str = "127.0.0.1"
    syslog_server_port: int = 514
    # transport: udp | tcp | tls
    transport: str = "tcp"
    # TLS options (used when transport == 'tls')
    tls_ca_file: str | None = None
    tls_cert_file: str | None = None
    tls_key_file: str | None = None
    tls_insecure: bool = False

class DiannaConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    # Base URL of Deep Instinct management console, e.g., https://di.example.com
    management_url: str = "https://selab-dpa.customers.deepinstinctweb.com"
    # API token for DIANNA REST API
    api_token: str | None = None
    # Verify TLS (set false to skip verification in dev)
    verify_tls: bool = True
    # Optional CA bundle path for custom CAs
    ca_bundle: str | None = None
    # Chunk size for uploads (bytes)
    chunk_size: int = 4 * 1024 * 1024
    # Request timeout (seconds)
    timeout: int = 60
    # Auto-enqueue analysis when verdict is malicious
    auto_on_malicious: bool = False

    # Result polling (after upload finishes)
    poll_results_enabled: bool = True
    poll_interval_seconds: int = 5
    # Maximum time to wait for a final result (seconds)
    poll_timeout_seconds: int = 900

    # Allow scientific notation or float-like env values for chunk_size (e.g., "4.194304e+06")
    @field_validator("chunk_size", mode="before")
    @classmethod
    def _coerce_chunk_size(cls, v):
        if v is None:
            return v
        if isinstance(v, int):
            return v
        try:
            # Accept floats or strings in scientific notation; coerce to int bytes
            # Use Decimal for robust parsing, then floor to int
            from decimal import Decimal

            return int(Decimal(str(v)))
        except Exception:
            # Fall back to default validation error path
            return v

    # Normalize management_url to include scheme if omitted
    @model_validator(mode="after")
    def _normalize_management_url(self):
        try:
            if self.management_url:
                url = str(self.management_url).strip()
                # If no scheme provided, default to https
                if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
                    self.management_url = f"https://{url}"
        except Exception:
            # Leave as-is on any parsing error
            pass
        return self


class CeleryTaskConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")
    broker: AnyUrl = "redis://redis:6379/5"
    backend: AnyUrl = "redis://redis:6379/6"
    scan_request_max_retries: int = 2
    dlq_expire_after_days: int = 7
    connector_retry_backoff_base: int = 60
    dsxa_retry_backoff_base: int = 2
    server_error_retry_backoff_base: int = 30
    retry_connector_connection_errors: bool = True
    retry_connector_server_errors: bool = True
    retry_connector_client_errors: bool = False
    retry_dsxa_connection_errors: bool = True
    retry_dsxa_timeout_errors: bool = True
    retry_dsxa_server_errors: bool = True
    retry_dsxa_client_errors: bool = False
    retry_queue_dispatch_errors: bool = False


# class SecurityConfig(BaseSettings):
#     model_config = SettingsConfigDict(env_nested_delimiter="__")
#     item_action_severity_threshold: DPASeverityEnum = DPASeverityEnum.MEDIUM


class DSXConnectConfig(BaseSettings):

    app_env: AppEnv = AppEnv.dev

    results_database: DatabaseConfig = DatabaseConfig()
    scanner: ScannerConfig = ScannerConfig()
    workers: CeleryTaskConfig = CeleryTaskConfig()

    # Feature flags
    class FeatureFlags(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter="__")
        enable_estimate_preflight: bool = False
        enable_approximate_estimates: bool = False

    features: FeatureFlags = FeatureFlags()

    # App datastore / pubsub (not Celery)
    # App Redis (job progress, pubsub). Results/stats DB may use a different Redis via database.loc.
    redis_url: AnyUrl = "redis://localhost:6379/3"
    syslog: SyslogConfig = SyslogConfig()
    dianna: DiannaConfig = DiannaConfig()

    # Outbound HMAC provisioned per-connector at registration; no global required

    # TLS/SSL for API server
    use_tls: bool = False
    tls_certfile: str | None = None
    tls_keyfile: str | None = None

    # Top-level settings config: env prefix + nested delimiter
    model_config = SettingsConfigDict(
        env_prefix="DSXCONNECT_",
        env_nested_delimiter="__",
    )

    # Ensure flat env overrides (used in local dev) are applied even when nested settings aliasing is finicky
    @model_validator(mode="after")
    def _apply_flat_results_db_env(self):
        try:
            env_db = os.getenv("DSXCONNECT_RESULTS_DB")
            if env_db:
                self.results_database.loc = env_db
            env_ret = os.getenv("DSXCONNECT_RESULTS_DB__RETAIN")
            if env_ret is not None and str(env_ret).strip() != "":
                try:
                    self.results_database.retain = int(env_ret)
                except Exception:
                    pass
        except Exception:
            pass
        return self


# Singleton accessor
from functools import lru_cache


@lru_cache
def get_config() -> DSXConnectConfig:
    if os.getenv("DSXCONNECT_SKIP_DEVENV", "").lower() not in ("1", "true", "yes"):
        load_devenv(Path(__file__).with_name('.dev.env'))
    return DSXConnectConfig()

@lru_cache
def get_auth_config() -> AuthConfig:
    return AuthConfig()

def reload_config() -> DSXConnectConfig:
    get_config.cache_clear()
    load_devenv(Path(__file__).with_name('.dev.env'))
    return get_config()


def app_env() -> str:
    # resolves to "dev" | "stg" | "prod"
    return get_config().app_env.value


# helper to grab the runtime environment
APP_ENV: Final = app_env()
