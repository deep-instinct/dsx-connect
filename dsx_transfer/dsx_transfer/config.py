from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dsx_transfer.models import TransferAction, TransferVerdict


class TransferConfigError(ValueError):
    pass


class TransferSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    policy_id: str | None = None


class SourceSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["filesystem"] = "filesystem"
    path: Path


class DestinationSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["auto", "filesystem", "gcs"] = "auto"
    uri: str


class DsxaScannerSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    auth_token: str | None = None
    protected_entity: int | None = None
    verify_tls: bool = True


class ScannerSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["static", "dsxa"] = "static"
    default_verdict: TransferVerdict = "benign"
    detect_eicar_test_file: bool = False
    verdicts_by_identity: dict[str, TransferVerdict] = Field(default_factory=dict)
    file_types_by_identity: dict[str, str] = Field(default_factory=dict)
    dsxa: DsxaScannerSection | None = None


class PolicySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict_actions: dict[TransferVerdict, TransferAction] = Field(default_factory=dict)
    file_type_actions: dict[str, TransferAction] = Field(default_factory=dict)


class RuntimeSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_jsonl: Path | None = None
    checkpoint: Path | None = None


class DsxTransferConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    transfer: TransferSection
    source: SourceSection
    destination: DestinationSection
    scanner: ScannerSection = Field(default_factory=ScannerSection)
    policy: PolicySection = Field(default_factory=PolicySection)
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)


def filesystem_to_gcs_config_template() -> str:
    return """version: 1

transfer:
  id: fs-to-gcs-demo
  policy_id: block-malicious

source:
  kind: filesystem
  path: /mnt/source-share

destination:
  kind: gcs
  uri: gs://customer-clean-bucket/archive

scanner:
  mode: dsxa
  dsxa:
    base_url: https://scanner.example.com

policy:
  verdict_actions:
    benign: allow
    malicious: block
    suspicious: block
    unknown: block
  file_type_actions:
    windows_executables: block

runtime:
  audit_jsonl: .dsx-transfer/audit/fs-to-gcs-demo.jsonl
  checkpoint: .dsx-transfer/checkpoints/fs-to-gcs-demo.json
"""


def load_transfer_config(path: Path) -> DsxTransferConfig:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise TransferConfigError("YAML config support requires PyYAML. Install dsx-transfer with its package dependencies.") from exc

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TransferConfigError(f"failed to read config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise TransferConfigError(f"failed to parse YAML config {path}: {exc}") from exc

    if raw is None:
        raise TransferConfigError(f"config {path} is empty")
    if not isinstance(raw, dict):
        raise TransferConfigError(f"config {path} must contain a YAML mapping at the top level")

    try:
        config = DsxTransferConfig.model_validate(raw)
    except ValueError as exc:
        raise TransferConfigError(f"invalid config {path}: {exc}") from exc

    return _resolve_config_paths(config, base_dir=path.resolve().parent)


def validate_transfer_config(path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    config: DsxTransferConfig | None = None

    try:
        config = load_transfer_config(path)
    except TransferConfigError as exc:
        errors.append(str(exc))

    if config is not None:
        if config.source.kind != "filesystem":
            errors.append(f"unsupported source kind: {config.source.kind}")
        if not config.source.path.exists():
            errors.append(f"source path does not exist: {config.source.path}")
        elif not config.source.path.is_dir():
            errors.append(f"source path is not a directory: {config.source.path}")

        destination_kind = config.destination.kind
        destination_uri = config.destination.uri
        if destination_kind == "gcs" or (destination_kind == "auto" and destination_uri.startswith("gs://")):
            if not _is_valid_gcs_uri(destination_uri):
                errors.append(f"invalid GCS destination URI: {destination_uri}")
            if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                warnings.append(
                    "GOOGLE_APPLICATION_CREDENTIALS is not set; validation cannot confirm Google ADC or workload identity."
                )
        elif destination_kind in {"auto", "filesystem"}:
            destination_path = Path(destination_uri)
            if destination_path.exists() and not destination_path.is_dir():
                errors.append(f"filesystem destination exists but is not a directory: {destination_path}")
        else:
            errors.append(f"unsupported destination kind: {destination_kind}")

        if config.scanner.mode == "dsxa":
            if config.scanner.dsxa is None:
                errors.append("scanner.mode is dsxa but scanner.dsxa is not configured")
            elif not config.scanner.dsxa.base_url:
                errors.append("scanner.dsxa.base_url is required")
        elif config.scanner.mode == "static" and config.scanner.dsxa is not None:
            warnings.append("scanner.dsxa is configured but scanner.mode is static")

        if config.policy.verdict_actions.get("unknown") == "allow":
            warnings.append("policy.verdict_actions.unknown=allow is useful for demos but weakens enforcement.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _resolve_config_paths(config: DsxTransferConfig, *, base_dir: Path) -> DsxTransferConfig:
    data = config.model_dump()
    source_path = config.source.path
    if not source_path.is_absolute():
        data["source"]["path"] = base_dir / source_path

    destination_uri = config.destination.uri
    if config.destination.kind in {"auto", "filesystem"} and not destination_uri.startswith("gs://"):
        destination_path = Path(destination_uri)
        if not destination_path.is_absolute():
            data["destination"]["uri"] = str(base_dir / destination_path)

    audit_jsonl = config.runtime.audit_jsonl
    if audit_jsonl is not None and not audit_jsonl.is_absolute():
        data["runtime"]["audit_jsonl"] = base_dir / audit_jsonl

    checkpoint = config.runtime.checkpoint
    if checkpoint is not None and not checkpoint.is_absolute():
        data["runtime"]["checkpoint"] = base_dir / checkpoint

    return DsxTransferConfig.model_validate(data)


def _is_valid_gcs_uri(uri: str) -> bool:
    if not uri.startswith("gs://"):
        return False
    remainder = uri.removeprefix("gs://")
    bucket, _, _prefix = remainder.partition("/")
    return bool(bucket)
