from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from dsx_connect_ng.readers.contracts import ReaderStrategy
from dsx_connect_ng.recovery import RecoveryMode


class FeatureFlags(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_FEATURES__",
        extra="ignore",
    )

    enable_control_plane: bool = True
    enable_scope_engine: bool = False
    enable_job_orchestration: bool = False
    enable_worker_readers: bool = False


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_POSTGRES__",
        extra="ignore",
    )

    url: str = Field(default="postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_ng")
    auto_apply_schema: bool = False


ControlPlaneBackend = Literal["auto", "memory", "postgres"]
JobBusBackend = Literal["auto", "memory", "rabbitmq"]
ScannerMode = Literal["stub", "dsxa", "auto"]
ResultSinkBackend = Literal["stdout", "json_lines"]


class RabbitMQSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_RABBITMQ__",
        extra="ignore",
    )

    url: str = Field(default="amqp://guest:guest@127.0.0.1:5672/")
    job_exchange: str = "dsx.ng.jobs"
    retry_exchange: str = "dsx.ng.jobs.retry"
    dead_letter_exchange: str = "dsx.ng.jobs.dlx"
    retry_max_attempts: int = 5
    retry_delay_ms: int = 5000


class RelaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_RELAY__",
        extra="ignore",
    )

    batch_size: int = 100
    poll_interval_seconds: float = 5.0


class ScannerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_SCANNER__",
        extra="ignore",
    )

    mode: ScannerMode = "stub"
    base_url: str = ""
    auth_token: str | None = None
    protected_entity: int | None = 1
    max_file_size_bytes: int = 2 * 1024 * 1024 * 1024
    verify_tls: bool = True
    timeout_seconds: float = 30.0


class ReaderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_READERS__",
        extra="ignore",
    )

    default_strategy: ReaderStrategy = "native"


class ResultSinkSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_RESULT_SINK__",
        extra="ignore",
    )

    backend: ResultSinkBackend = "stdout"
    path: str = "/tmp/dsx-connect-ng-results.jsonl"


class RecoverySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG_RECOVERY__",
        extra="ignore",
    )

    mode: RecoveryMode = "batch"
    batch_size: int = 100
    checkpoint_every_items: int | None = None
    checkpoint_every_seconds: int | None = None
    large_object_threshold_bytes: int | None = None
    prefer_item_mode_for_archives: bool = True


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DSX_CONNECT_NG__",
        extra="ignore",
    )

    service_name: str = "dsx-connect-ng"
    environment: str = "dev"
    api_prefix: str = "/api/v1"
    control_plane_backend: ControlPlaneBackend = "auto"
    job_bus_backend: JobBusBackend = "memory"
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    rabbitmq: RabbitMQSettings = Field(default_factory=RabbitMQSettings)
    relay: RelaySettings = Field(default_factory=RelaySettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)
    readers: ReaderSettings = Field(default_factory=ReaderSettings)
    result_sink: ResultSinkSettings = Field(default_factory=ResultSinkSettings)
    recovery: RecoverySettings = Field(default_factory=RecoverySettings)


settings = AppSettings()
