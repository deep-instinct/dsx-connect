from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from dsx_transfer.adapters import FilesystemSinkAdapter, FilesystemSourceAdapter, GcsSinkAdapter, parse_gcs_uri
from dsx_transfer.audit import JsonLinesAuditSink
from dsx_transfer.checkpoint import JsonCheckpointStore
from dsx_transfer.config import (
    DsxTransferConfig,
    TransferConfigError,
    filesystem_to_gcs_config_template,
    load_transfer_config,
    validate_transfer_config,
)
from dsx_transfer.dsxa_file_types import FILE_TYPE_GROUPS
from dsx_transfer.dsxa_scan_gate import DsxaStreamScanGate
from dsx_transfer.engine import TransferEngine
from dsx_transfer.models import TransferAction, TransferVerdict
from dsx_transfer.policy import GuardedTransferPolicy
from dsx_transfer.scan_gates import StaticVerdictScanGate


app = typer.Typer(
    add_completion=False,
    help="Run guarded file transfers with a pre-commit scan gate.",
)
config_app = typer.Typer(
    add_completion=False,
    help="Create, validate, and inspect DSX-Transfer config files.",
)
app.add_typer(config_app, name="config")


@app.callback()
def root() -> None:
    """Run guarded file transfers with a pre-commit scan gate."""


@config_app.command("schema")
def config_schema() -> None:
    """Print the dsx-transfer.yaml JSON Schema."""
    sys.stdout.write(json.dumps(DsxTransferConfig.model_json_schema(), indent=2, sort_keys=True))
    sys.stdout.write("\n")


@config_app.command("init")
def config_init(
    output: Annotated[Path, typer.Option("--output", "-o", help="Config file path to create.")] = Path("dsx-transfer.yaml"),
    preset: Annotated[str, typer.Option("--preset", help="Config preset to generate.")] = "filesystem-to-gcs",
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config file.")] = False,
) -> None:
    """Create a starter dsx-transfer.yaml config."""
    if preset != "filesystem-to-gcs":
        raise typer.BadParameter("unsupported config preset; expected filesystem-to-gcs")
    if output.exists() and not force:
        raise typer.BadParameter(f"config already exists: {output}; pass --force to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(filesystem_to_gcs_config_template(), encoding="utf-8")
    sys.stdout.write(f"created {output}\n")


@config_app.command("validate")
def config_validate(
    config: Annotated[Path, typer.Option("--config", "-c", help="Path to a dsx-transfer YAML config file.")] = Path(
        "dsx-transfer.yaml"
    ),
) -> None:
    """Validate a dsx-transfer.yaml config and print JSON diagnostics."""
    result = validate_transfer_config(config)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
    sys.stdout.write("\n")
    if not result["valid"]:
        raise typer.Exit(1)


def _verdict_choices() -> set[str]:
    return {"benign", "malicious", "suspicious", "unknown", "error"}


def _action_choices() -> set[str]:
    return {"allow", "block", "exclude", "quarantine", "manual_review", "error"}


def _scanner_modes() -> set[str]:
    return {"static", "dsxa"}


def _destination_kinds() -> set[str]:
    return {"auto", "filesystem", "gcs"}


def _sftpgo_block_responses() -> set[str]:
    return {"reject", "allow_after_remove"}


def parse_verdict_overrides(values: list[str]) -> dict[str, TransferVerdict]:
    overrides: dict[str, TransferVerdict] = {}
    valid = _verdict_choices()
    for value in values:
        if "=" not in value:
            raise typer.BadParameter(f"invalid verdict override {value!r}; expected OBJECT=VERDICT")
        identity, verdict = value.split("=", 1)
        identity = identity.strip()
        verdict = verdict.strip()
        if not identity:
            raise typer.BadParameter(f"invalid verdict override {value!r}; object identity is empty")
        if verdict not in valid:
            raise typer.BadParameter(f"invalid verdict {verdict!r}; expected one of {', '.join(sorted(valid))}")
        overrides[identity] = verdict  # type: ignore[assignment]
    return overrides


def parse_file_type_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter(f"invalid file type override {value!r}; expected OBJECT=FILE_TYPE")
        identity, file_type = value.split("=", 1)
        identity = identity.strip()
        file_type = file_type.strip()
        if not identity:
            raise typer.BadParameter(f"invalid file type override {value!r}; object identity is empty")
        if not file_type:
            raise typer.BadParameter(f"invalid file type override {value!r}; file type is empty")
        overrides[identity] = file_type
    return overrides


def parse_file_type_actions(values: list[str]) -> dict[str, TransferAction]:
    actions: dict[str, TransferAction] = {}
    valid = _action_choices()
    for value in values:
        if "=" not in value:
            raise typer.BadParameter(f"invalid file type action {value!r}; expected DSXA_FILE_TYPE_OR_GROUP=ACTION")
        file_type, action = value.split("=", 1)
        file_type = file_type.strip()
        action = action.strip()
        if not file_type:
            raise typer.BadParameter(f"invalid file type action {value!r}; file type is empty")
        if action not in valid:
            raise typer.BadParameter(f"invalid action {action!r}; expected one of {', '.join(sorted(valid))}")
        actions[file_type] = action  # type: ignore[assignment]
    return actions


def parse_verdict_actions(values: list[str]) -> dict[TransferVerdict, TransferAction]:
    actions: dict[TransferVerdict, TransferAction] = {}
    valid_verdicts = _verdict_choices()
    valid_actions = _action_choices()
    for value in values:
        if "=" not in value:
            raise typer.BadParameter(f"invalid verdict action {value!r}; expected VERDICT=ACTION")
        verdict, action = value.split("=", 1)
        verdict = verdict.strip()
        action = action.strip()
        if verdict not in valid_verdicts:
            raise typer.BadParameter(f"invalid verdict {verdict!r}; expected one of {', '.join(sorted(valid_verdicts))}")
        if action not in valid_actions:
            raise typer.BadParameter(f"invalid action {action!r}; expected one of {', '.join(sorted(valid_actions))}")
        actions[verdict] = action  # type: ignore[assignment]
    return actions


def _async_dsxa_client_class():
    try:
        from dsxa_sdk_py.client import AsyncDSXAClient
    except ModuleNotFoundError as exc:
        raise typer.BadParameter(
            "DSXA mode requires dsxa-sdk-py. Install it with "
            "`./.venv/bin/python -m pip install -e ./dsxa_sdk_py -e ./dsx_transfer`, "
            "or run from source with `PYTHONPATH=dsx_transfer:dsxa_sdk_py`."
        ) from exc
    return AsyncDSXAClient


def _resolve_migrate_settings(
    *,
    config: Path | None,
    source: Path | None,
    destination: str | None,
    destination_kind: str | None,
    transfer_id: str | None,
    policy_id: str | None,
    scanner_mode: str | None,
    default_verdict: str | None,
    verdicts_by_identity: dict[str, TransferVerdict],
    file_types_by_identity: dict[str, str],
    file_type_actions: dict[str, TransferAction],
    verdict_actions: dict[TransferVerdict, TransferAction],
    detect_eicar_test_file: bool,
    dsxa_base_url: str | None,
    dsxa_auth_token: str | None,
    dsxa_protected_entity: int | None,
    dsxa_verify_tls: bool,
    audit_jsonl: Path | None,
    checkpoint: Path | None,
    concurrency: int | None,
) -> dict:
    settings = {
        "source": source,
        "destination": destination,
        "destination_kind": destination_kind or "auto",
        "transfer_id": transfer_id,
        "policy_id": policy_id,
        "scanner_mode": scanner_mode or "static",
        "default_verdict": default_verdict or "benign",
        "verdicts_by_identity": verdicts_by_identity,
        "file_types_by_identity": file_types_by_identity,
        "file_type_actions": file_type_actions,
        "verdict_actions": verdict_actions,
        "detect_eicar_test_file": detect_eicar_test_file,
        "dsxa_base_url": dsxa_base_url,
        "dsxa_auth_token": dsxa_auth_token,
        "dsxa_protected_entity": dsxa_protected_entity,
        "dsxa_verify_tls": dsxa_verify_tls,
        "audit_jsonl": audit_jsonl,
        "checkpoint": checkpoint,
        "concurrency": concurrency or 1,
    }

    if config is not None:
        transfer_config = load_transfer_config(config)
        dsxa = transfer_config.scanner.dsxa
        settings.update(
            {
                "source": transfer_config.source.path,
                "destination": transfer_config.destination.uri,
                "destination_kind": transfer_config.destination.kind,
                "transfer_id": transfer_config.transfer.id,
                "policy_id": transfer_config.transfer.policy_id,
                "scanner_mode": transfer_config.scanner.mode,
                "default_verdict": transfer_config.scanner.default_verdict,
                "verdicts_by_identity": transfer_config.scanner.verdicts_by_identity,
                "file_types_by_identity": transfer_config.scanner.file_types_by_identity,
                "file_type_actions": transfer_config.policy.file_type_actions,
                "verdict_actions": transfer_config.policy.verdict_actions,
                "detect_eicar_test_file": transfer_config.scanner.detect_eicar_test_file,
                "dsxa_base_url": dsxa.base_url if dsxa else None,
                "dsxa_auth_token": dsxa.auth_token if dsxa else None,
                "dsxa_protected_entity": dsxa.protected_entity if dsxa else None,
                "dsxa_verify_tls": dsxa.verify_tls if dsxa else True,
                "audit_jsonl": transfer_config.runtime.audit_jsonl,
                "checkpoint": transfer_config.runtime.checkpoint,
                "concurrency": transfer_config.runtime.concurrency,
            }
        )

        if source is not None:
            settings["source"] = source
        if destination is not None:
            settings["destination"] = destination
        if destination_kind is not None:
            settings["destination_kind"] = destination_kind
        if transfer_id is not None:
            settings["transfer_id"] = transfer_id
        if policy_id is not None:
            settings["policy_id"] = policy_id
        if scanner_mode is not None:
            settings["scanner_mode"] = scanner_mode
        if default_verdict is not None:
            settings["default_verdict"] = default_verdict
        if verdicts_by_identity:
            settings["verdicts_by_identity"] = verdicts_by_identity
        if file_types_by_identity:
            settings["file_types_by_identity"] = file_types_by_identity
        if file_type_actions:
            settings["file_type_actions"] = file_type_actions
        if verdict_actions:
            settings["verdict_actions"] = verdict_actions
        if detect_eicar_test_file:
            settings["detect_eicar_test_file"] = detect_eicar_test_file
        if dsxa_base_url is not None:
            settings["dsxa_base_url"] = dsxa_base_url
        if dsxa_auth_token is not None:
            settings["dsxa_auth_token"] = dsxa_auth_token
        if dsxa_protected_entity is not None:
            settings["dsxa_protected_entity"] = dsxa_protected_entity
        if not dsxa_verify_tls:
            settings["dsxa_verify_tls"] = dsxa_verify_tls
        if audit_jsonl is not None:
            settings["audit_jsonl"] = audit_jsonl
        if checkpoint is not None:
            settings["checkpoint"] = checkpoint
        if concurrency is not None:
            settings["concurrency"] = concurrency

    missing = [name for name in ("source", "destination", "transfer_id") if settings[name] is None]
    if missing:
        raise typer.BadParameter(f"missing required migrate input(s): {', '.join(missing)}; provide them as options or --config")

    return settings


@app.command()
def migrate(
    config: Annotated[Path | None, typer.Option("--config", help="Path to a dsx-transfer YAML config file.")] = None,
    source: Annotated[Path | None, typer.Option("--source", help="Source filesystem directory.")] = None,
    destination: Annotated[str | None, typer.Option("--destination", help="Destination directory or gs://bucket/prefix URI.")] = None,
    transfer_id: Annotated[str | None, typer.Option("--transfer-id", help="Stable transfer ID for audit and checkpoint records.")] = None,
    destination_kind: Annotated[
        str | None,
        typer.Option("--destination-kind", help="Destination kind: auto, filesystem, or gcs."),
    ] = None,
    policy_id: Annotated[str | None, typer.Option("--policy-id", help="Policy ID to stamp on scan decisions.")] = None,
    default_verdict: Annotated[
        str | None,
        typer.Option("--default-verdict", help="Default static scan verdict."),
    ] = None,
    scanner_mode: Annotated[
        str | None,
        typer.Option("--scanner-mode", help="Scanner mode: static or dsxa."),
    ] = None,
    dsxa_base_url: Annotated[str | None, typer.Option("--dsxa-base-url", help="DSXA base URL for stream scanning.")] = None,
    dsxa_auth_token: Annotated[str | None, typer.Option("--dsxa-auth-token", help="Optional DSXA auth token.")] = None,
    dsxa_protected_entity: Annotated[int | None, typer.Option("--dsxa-protected-entity", help="Optional DSXA protected entity ID.")] = None,
    dsxa_verify_tls: Annotated[bool, typer.Option("--dsxa-verify-tls/--dsxa-no-verify-tls", help="Verify DSXA TLS certificates.")] = True,
    verdict: Annotated[
        list[str] | None,
        typer.Option("--verdict", help="Override static verdict for an object identity. Format: OBJECT=VERDICT."),
    ] = None,
    file_type: Annotated[
        list[str] | None,
        typer.Option("--file-type", help="Override detected file type for an object identity. Format: OBJECT=FILE_TYPE."),
    ] = None,
    file_type_action: Annotated[
        list[str] | None,
        typer.Option(
            "--file-type-action",
            help=f"Set policy action for a DSXA detected file type or group. Groups: {', '.join(sorted(FILE_TYPE_GROUPS))}.",
        ),
    ] = None,
    verdict_action: Annotated[
        list[str] | None,
        typer.Option("--verdict-action", help="Set policy action for a scanner verdict. Format: VERDICT=ACTION."),
    ] = None,
    detect_eicar_test_file: Annotated[
        bool,
        typer.Option(
            "--detect-eicar-test-file/--no-detect-eicar-test-file",
            help="Demo/test mode: mark the EICAR antivirus test file signature as malicious when using the static scanner.",
        ),
    ] = False,
    audit_jsonl: Annotated[Path | None, typer.Option("--audit-jsonl", help="Path to append JSONL audit events.")] = None,
    checkpoint: Annotated[Path | None, typer.Option("--checkpoint", help="Path to JSON checkpoint state.")] = None,
    concurrency: Annotated[int | None, typer.Option("--concurrency", min=1, help="Maximum file transfer concurrency.")] = None,
    progress_jsonl: Annotated[
        bool,
        typer.Option("--progress-jsonl/--no-progress-jsonl", help="Emit transfer progress events as JSON Lines on stderr."),
    ] = False,
) -> None:
    try:
        settings = _resolve_migrate_settings(
            config=config,
            source=source,
            destination=destination,
            destination_kind=destination_kind,
            transfer_id=transfer_id,
            policy_id=policy_id,
            scanner_mode=scanner_mode,
            default_verdict=default_verdict,
            verdicts_by_identity=parse_verdict_overrides(verdict or []),
            file_types_by_identity=parse_file_type_overrides(file_type or []),
            file_type_actions=parse_file_type_actions(file_type_action or []),
            verdict_actions=parse_verdict_actions(verdict_action or []),
            detect_eicar_test_file=detect_eicar_test_file,
            dsxa_base_url=dsxa_base_url,
            dsxa_auth_token=dsxa_auth_token,
            dsxa_protected_entity=dsxa_protected_entity,
            dsxa_verify_tls=dsxa_verify_tls,
            audit_jsonl=audit_jsonl,
            checkpoint=checkpoint,
            concurrency=concurrency,
        )
    except TransferConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if settings["default_verdict"] not in _verdict_choices():
        raise typer.BadParameter(f"invalid default verdict {settings['default_verdict']!r}")
    if settings["scanner_mode"] not in _scanner_modes():
        raise typer.BadParameter(
            f"invalid scanner mode {settings['scanner_mode']!r}; expected one of {', '.join(sorted(_scanner_modes()))}"
        )
    if settings["destination_kind"] not in _destination_kinds():
        raise typer.BadParameter(
            f"invalid destination kind {settings['destination_kind']!r}; expected one of {', '.join(sorted(_destination_kinds()))}"
        )
    if settings["scanner_mode"] == "dsxa" and not settings["dsxa_base_url"]:
        raise typer.BadParameter("--dsxa-base-url is required when --scanner-mode dsxa")
    try:
        report = asyncio.run(
            _run_migrate(
                **settings,
                progress_jsonl=progress_jsonl,
            )
        )
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not report.outcomes:
        sys.stderr.write(f"warning: transfer plan contains no files under source {settings['source']}\n")
    sys.stdout.write(report.model_dump_json())
    sys.stdout.write("\n")
    if report.failed_count:
        raise typer.Exit(1)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Host interface for the decision service.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port for the decision service.")] = 8088,
    policy_id: Annotated[str | None, typer.Option("--policy-id", help="Policy ID to stamp on scan decisions.")] = None,
    default_verdict: Annotated[
        str,
        typer.Option("--default-verdict", help="Default static scan verdict."),
    ] = "benign",
    verdict: Annotated[
        list[str] | None,
        typer.Option("--verdict", help="Override static verdict for an object identity. Format: OBJECT=VERDICT."),
    ] = None,
    file_type: Annotated[
        list[str] | None,
        typer.Option("--file-type", help="Override detected file type for an object identity. Format: OBJECT=FILE_TYPE."),
    ] = None,
    file_type_action: Annotated[
        list[str] | None,
        typer.Option(
            "--file-type-action",
            help=f"Set policy action for a DSXA detected file type or group. Groups: {', '.join(sorted(FILE_TYPE_GROUPS))}.",
        ),
    ] = None,
    verdict_action: Annotated[
        list[str] | None,
        typer.Option("--verdict-action", help="Set policy action for a scanner verdict. Format: VERDICT=ACTION."),
    ] = None,
    detect_eicar_test_file: Annotated[
        bool,
        typer.Option(
            "--detect-eicar-test-file/--no-detect-eicar-test-file",
            help="Demo/test mode: mark the EICAR antivirus test file signature as malicious when using the static scanner.",
        ),
    ] = False,
    scanner_mode: Annotated[
        str,
        typer.Option("--scanner-mode", help="Scanner mode: static or dsxa."),
    ] = "static",
    dsxa_base_url: Annotated[str | None, typer.Option("--dsxa-base-url", help="DSXA base URL for stream scanning.")] = None,
    dsxa_auth_token: Annotated[str | None, typer.Option("--dsxa-auth-token", help="Optional DSXA auth token.")] = None,
    dsxa_protected_entity: Annotated[int | None, typer.Option("--dsxa-protected-entity", help="Optional DSXA protected entity ID.")] = None,
    dsxa_verify_tls: Annotated[bool, typer.Option("--dsxa-verify-tls/--dsxa-no-verify-tls", help="Verify DSXA TLS certificates.")] = True,
    sftpgo_storage_root: Annotated[
        Path | None,
        typer.Option("--sftpgo-storage-root", help="Host path for SFTPGo storage, used by the upload hook to read uploaded bytes."),
    ] = None,
    sftpgo_container_root: Annotated[
        str,
        typer.Option("--sftpgo-container-root", help="SFTPGo container path that maps to --sftpgo-storage-root."),
    ] = "/srv/sftpgo/data",
    remove_blocked_uploads: Annotated[
        bool,
        typer.Option("--remove-blocked-uploads/--keep-blocked-uploads", help="Remove files blocked by the SFTPGo upload hook."),
    ] = True,
    sftpgo_block_response: Annotated[
        str,
        typer.Option(
            "--sftpgo-block-response",
            help="SFTPGo upload hook response for blocked files: reject or allow_after_remove.",
        ),
    ] = "reject",
    audit_jsonl: Annotated[Path | None, typer.Option("--audit-jsonl", help="Path to append JSONL audit events.")] = None,
) -> None:
    import uvicorn

    if default_verdict not in _verdict_choices():
        raise typer.BadParameter(f"invalid default verdict {default_verdict!r}")
    if scanner_mode not in _scanner_modes():
        raise typer.BadParameter(f"invalid scanner mode {scanner_mode!r}; expected one of {', '.join(sorted(_scanner_modes()))}")
    if sftpgo_block_response not in _sftpgo_block_responses():
        raise typer.BadParameter(
            f"invalid SFTPGo block response {sftpgo_block_response!r}; "
            f"expected one of {', '.join(sorted(_sftpgo_block_responses()))}"
        )

    from dsx_transfer.app import create_app

    policy = GuardedTransferPolicy(
        policy_id=policy_id,
        verdict_actions=parse_verdict_actions(verdict_action or []),
        file_type_actions=parse_file_type_actions(file_type_action or []),
    )
    if scanner_mode == "dsxa":
        if not dsxa_base_url:
            raise typer.BadParameter("--dsxa-base-url is required when --scanner-mode dsxa")
        AsyncDSXAClient = _async_dsxa_client_class()

        client = AsyncDSXAClient(
            base_url=dsxa_base_url,
            auth_token=dsxa_auth_token,
            verify_tls=dsxa_verify_tls,
            default_protected_entity=dsxa_protected_entity,
        )
        scan_gate = DsxaStreamScanGate(
            client,
            policy=policy,
            protected_entity=dsxa_protected_entity,
        )
        service_app = create_app(
            scan_gate=scan_gate,
            audit_sink=JsonLinesAuditSink(audit_jsonl) if audit_jsonl else None,
            sftpgo_storage_root=sftpgo_storage_root,
            sftpgo_container_root=sftpgo_container_root,
            remove_blocked_uploads=remove_blocked_uploads,
            sftpgo_block_response=sftpgo_block_response,
        )

        @service_app.on_event("shutdown")
        async def close_dsxa_client() -> None:
            await client.aclose()

        uvicorn.run(service_app, host=host, port=port)
        return

    scan_gate = StaticVerdictScanGate(
        default_verdict=default_verdict,  # type: ignore[arg-type]
        verdicts_by_identity=parse_verdict_overrides(verdict or []),
        file_types_by_identity=parse_file_type_overrides(file_type or []),
        policy=policy,
        detect_eicar_test_file=detect_eicar_test_file,
    )
    uvicorn.run(
        create_app(
            scan_gate=scan_gate,
            audit_sink=JsonLinesAuditSink(audit_jsonl) if audit_jsonl else None,
            sftpgo_storage_root=sftpgo_storage_root,
            sftpgo_container_root=sftpgo_container_root,
            remove_blocked_uploads=remove_blocked_uploads,
            sftpgo_block_response=sftpgo_block_response,
        ),
        host=host,
        port=port,
    )


async def _run_migrate(
    *,
    source: Path,
    destination: str,
    destination_kind: str,
    transfer_id: str,
    policy_id: str | None,
    scanner_mode: str,
    default_verdict: TransferVerdict,
    verdicts_by_identity: dict[str, TransferVerdict],
    file_types_by_identity: dict[str, str],
    file_type_actions: dict[str, TransferAction],
    verdict_actions: dict[TransferVerdict, TransferAction],
    detect_eicar_test_file: bool,
    dsxa_base_url: str | None,
    dsxa_auth_token: str | None,
    dsxa_protected_entity: int | None,
    dsxa_verify_tls: bool,
    audit_jsonl: Path | None,
    checkpoint: Path | None,
    concurrency: int,
    progress_jsonl: bool,
):
    async def emit_progress(completed: int, total: int, outcome) -> None:
        if not progress_jsonl:
            return
        event = {
            "event": "transfer_progress",
            "transfer_id": transfer_id,
            "completed_items": completed,
            "total_items": total,
            "percent_complete": round((completed / total) * 100, 3) if total else 100.0,
            "state": outcome.state,
            "object_identity": outcome.item.object_identity,
        }
        sys.stderr.write(json.dumps(event, sort_keys=True))
        sys.stderr.write("\n")
        sys.stderr.flush()

    policy = GuardedTransferPolicy(
        policy_id=policy_id,
        verdict_actions=verdict_actions,
        file_type_actions=file_type_actions,
    )
    if scanner_mode == "dsxa":
        AsyncDSXAClient = _async_dsxa_client_class()

        async with AsyncDSXAClient(
            base_url=str(dsxa_base_url),
            auth_token=dsxa_auth_token,
            verify_tls=dsxa_verify_tls,
            default_protected_entity=dsxa_protected_entity,
        ) as client:
            engine = _build_engine(
                source=source,
                destination=destination,
                destination_kind=destination_kind,
                scan_gate=DsxaStreamScanGate(
                    client,
                    policy=policy,
                    protected_entity=dsxa_protected_entity,
                ),
                audit_jsonl=audit_jsonl,
                checkpoint=checkpoint,
                concurrency=concurrency,
                progress_callback=emit_progress if progress_jsonl else None,
            )
            return await engine.run(
                destination_uri=_destination_uri(destination, destination_kind),
                transfer_id=transfer_id,
                policy_id=policy_id,
            )

    scan_gate = StaticVerdictScanGate(
        default_verdict=default_verdict,
        verdicts_by_identity=verdicts_by_identity,
        file_types_by_identity=file_types_by_identity,
        policy=policy,
        detect_eicar_test_file=detect_eicar_test_file,
    )
    engine = _build_engine(
        source=source,
        destination=destination,
        destination_kind=destination_kind,
        scan_gate=scan_gate,
        audit_jsonl=audit_jsonl,
        checkpoint=checkpoint,
        concurrency=concurrency,
        progress_callback=emit_progress if progress_jsonl else None,
    )
    return await engine.run(
        destination_uri=_destination_uri(destination, destination_kind),
        transfer_id=transfer_id,
        policy_id=policy_id,
    )


def _build_static_scan_gate(
    *,
    policy_id: str | None,
    default_verdict: TransferVerdict,
    verdicts_by_identity: dict[str, TransferVerdict],
    file_types_by_identity: dict[str, str],
    file_type_actions: dict[str, TransferAction],
    verdict_actions: dict[TransferVerdict, TransferAction],
    detect_eicar_test_file: bool = False,
) -> StaticVerdictScanGate:
    return StaticVerdictScanGate(
        default_verdict=default_verdict,
        verdicts_by_identity=verdicts_by_identity,
        file_types_by_identity=file_types_by_identity,
        policy=GuardedTransferPolicy(
            policy_id=policy_id,
            verdict_actions=verdict_actions,
            file_type_actions=file_type_actions,
        ),
        detect_eicar_test_file=detect_eicar_test_file,
    )


def _build_engine(
    *,
    source: Path,
    destination: str,
    destination_kind: str,
    scan_gate,
    audit_jsonl: Path | None,
    checkpoint: Path | None,
    concurrency: int,
    progress_callback=None,
) -> TransferEngine:
    engine = TransferEngine(
        source=FilesystemSourceAdapter(source),
        sink=_build_sink(destination=destination, destination_kind=destination_kind),
        scan_gate=scan_gate,
        audit_sink=JsonLinesAuditSink(audit_jsonl) if audit_jsonl else None,
        checkpoint_store=JsonCheckpointStore(checkpoint) if checkpoint else None,
        concurrency=concurrency,
        progress_callback=progress_callback,
    )
    return engine


def _resolve_destination_kind(destination: str, destination_kind: str) -> str:
    if destination_kind == "auto":
        return "gcs" if destination.startswith("gs://") else "filesystem"
    return destination_kind


def _build_sink(*, destination: str, destination_kind: str):
    resolved_kind = _resolve_destination_kind(destination, destination_kind)
    if resolved_kind == "gcs":
        return GcsSinkAdapter(parse_gcs_uri(destination))
    if resolved_kind == "filesystem":
        return FilesystemSinkAdapter(Path(destination))
    raise ValueError(f"unsupported destination kind: {destination_kind}")


def _destination_uri(destination: str, destination_kind: str) -> str:
    resolved_kind = _resolve_destination_kind(destination, destination_kind)
    if resolved_kind == "gcs":
        return parse_gcs_uri(destination).uri
    if resolved_kind == "filesystem":
        return Path(destination).resolve().as_uri()
    raise ValueError(f"unsupported destination kind: {destination_kind}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
