from __future__ import annotations

import json
from pathlib import Path
import builtins

from typer.testing import CliRunner

from dsx_transfer.cli import _async_dsxa_client_class, _destination_uri, _resolve_destination_kind, app
import typer


runner = CliRunner()


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_cli_migrate_blocks_static_malicious_verdict(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    audit_path = tmp_path / "audit.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    write_file(source_root / "clean.txt", b"clean")
    write_file(source_root / "bad.exe", b"malware")

    result = runner.invoke(
        app,
        [
            "migrate",
            "--source",
            str(source_root),
            "--destination",
            str(destination_root),
            "--transfer-id",
            "transfer-cli",
            "--policy-id",
            "policy-cli",
            "--verdict",
            "bad.exe=malicious",
            "--audit-jsonl",
            str(audit_path),
            "--checkpoint",
            str(checkpoint_path),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["transfer_id"] == "transfer-cli"
    assert report["planned_count"] == 2
    assert report["allowed_count"] == 1
    assert report["blocked_count"] == 1
    assert report["failed_count"] == 0
    assert [outcome["state"] for outcome in report["outcomes"]] == ["blocked", "allowed"]
    assert not (destination_root / "bad.exe").exists()
    assert (destination_root / "clean.txt").read_bytes() == b"clean"
    assert [event["state"] for event in load_jsonl(audit_path)] == ["blocked", "allowed"]


def test_cli_migrate_reads_transfer_config(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    audit_path = tmp_path / ".dsx-transfer" / "audit.jsonl"
    checkpoint_path = tmp_path / ".dsx-transfer" / "checkpoint.json"
    config_path = tmp_path / "dsx-transfer.yaml"
    write_file(source_root / "clean.txt", b"clean")
    write_file(source_root / "bad.exe", b"malware")
    config_path.write_text(
        f"""
version: 1
transfer:
  id: config-transfer
  policy_id: config-policy
source:
  kind: filesystem
  path: {source_root}
destination:
  kind: filesystem
  uri: {destination_root}
scanner:
  mode: static
  verdicts_by_identity:
    bad.exe: malicious
policy:
  verdict_actions:
    malicious: block
runtime:
  audit_jsonl: {audit_path}
  checkpoint: {checkpoint_path}
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["migrate", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["transfer_id"] == "config-transfer"
    assert report["policy_id"] == "config-policy"
    assert report["planned_count"] == 2
    assert report["allowed_count"] == 1
    assert report["blocked_count"] == 1
    assert [outcome["state"] for outcome in report["outcomes"]] == ["blocked", "allowed"]
    assert not (destination_root / "bad.exe").exists()
    assert (destination_root / "clean.txt").read_bytes() == b"clean"
    assert [event["state"] for event in load_jsonl(audit_path)] == ["blocked", "allowed"]
    assert checkpoint_path.exists()


def test_cli_migrate_resolves_config_relative_paths(tmp_path: Path) -> None:
    config_dir = tmp_path / "workspace"
    source_root = config_dir / "source"
    destination_root = config_dir / "destination"
    config_path = config_dir / "dsx-transfer.yaml"
    write_file(source_root / "clean.txt", b"clean")
    config_path.write_text(
        """
version: 1
transfer:
  id: relative-config-transfer
source:
  path: source
destination:
  uri: destination
runtime:
  audit_jsonl: .dsx-transfer/audit.jsonl
  checkpoint: .dsx-transfer/checkpoint.json
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["migrate", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert (destination_root / "clean.txt").read_bytes() == b"clean"
    assert (config_dir / ".dsx-transfer" / "audit.jsonl").exists()
    assert (config_dir / ".dsx-transfer" / "checkpoint.json").exists()


def test_cli_migrate_requires_options_or_config() -> None:
    result = runner.invoke(app, ["migrate"])

    assert result.exit_code != 0
    assert "missing required migrate input" in result.output


def test_cli_config_schema_outputs_json_schema() -> None:
    result = runner.invoke(app, ["config", "schema"])

    assert result.exit_code == 0, result.output
    schema = json.loads(result.stdout)
    assert schema["title"] == "DsxTransferConfig"
    assert "transfer" in schema["properties"]
    assert "source" in schema["properties"]
    assert "destination" in schema["properties"]


def test_cli_config_init_writes_filesystem_to_gcs_template(tmp_path: Path) -> None:
    config_path = tmp_path / "dsx-transfer.yaml"

    result = runner.invoke(app, ["config", "init", "--output", str(config_path)])

    assert result.exit_code == 0, result.output
    text = config_path.read_text(encoding="utf-8")
    assert "version: 1" in text
    assert "kind: gcs" in text
    assert "gs://customer-clean-bucket/archive" in text

    second = runner.invoke(app, ["config", "init", "--output", str(config_path)])
    assert second.exit_code != 0
    assert "already exists" in second.output

    forced = runner.invoke(app, ["config", "init", "--output", str(config_path), "--force"])
    assert forced.exit_code == 0, forced.output


def test_cli_config_validate_reports_valid_config(tmp_path: Path, monkeypatch) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    service_account = tmp_path / "service-account.json"
    service_account.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(service_account))
    config_path = tmp_path / "dsx-transfer.yaml"
    config_path.write_text(
        f"""
version: 1
transfer:
  id: validate-transfer
source:
  path: {source_root}
destination:
  kind: gcs
  uri: gs://clean-bucket/archive
scanner:
  mode: dsxa
  dsxa:
    base_url: http://127.0.0.1:15000
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    diagnostics = json.loads(result.stdout)
    assert diagnostics == {"errors": [], "valid": True, "warnings": []}


def test_cli_config_validate_reports_errors_and_warnings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    config_path = tmp_path / "dsx-transfer.yaml"
    config_path.write_text(
        """
version: 1
transfer:
  id: validate-transfer
source:
  path: missing-source
destination:
  kind: gcs
  uri: gs://clean-bucket/archive
scanner:
  mode: dsxa
policy:
  verdict_actions:
    unknown: allow
""".lstrip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["config", "validate", "--config", str(config_path)])

    assert result.exit_code == 1, result.output
    diagnostics = json.loads(result.stdout)
    assert diagnostics["valid"] is False
    assert any("source path does not exist" in error for error in diagnostics["errors"])
    assert "scanner.mode is dsxa but scanner.dsxa is not configured" in diagnostics["errors"]
    assert any("GOOGLE_APPLICATION_CREDENTIALS is not set" in warning for warning in diagnostics["warnings"])
    assert any("unknown=allow" in warning for warning in diagnostics["warnings"])


def test_cli_migrate_uses_checkpoint_resume(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    audit_path = tmp_path / "audit.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    write_file(source_root / "clean.txt", b"clean")

    base_args = [
        "migrate",
        "--source",
        str(source_root),
        "--destination",
        str(destination_root),
        "--transfer-id",
        "transfer-resume-cli",
        "--policy-id",
        "policy-resume-cli",
        "--audit-jsonl",
        str(audit_path),
        "--checkpoint",
        str(checkpoint_path),
    ]
    first = runner.invoke(app, base_args)
    assert first.exit_code == 0, first.output
    (destination_root / "clean.txt").write_bytes(b"existing")

    second = runner.invoke(app, [*base_args, "--default-verdict", "malicious"])

    assert second.exit_code == 0, second.output
    report = json.loads(second.stdout)
    assert [outcome["state"] for outcome in report["outcomes"]] == ["skipped"]
    assert (destination_root / "clean.txt").read_bytes() == b"existing"
    assert [event["state"] for event in load_jsonl(audit_path)] == ["allowed", "skipped"]


def test_cli_migrate_applies_detected_file_type_action(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    write_file(source_root / "payload.bin", b"content")

    result = runner.invoke(
        app,
        [
            "migrate",
            "--source",
            str(source_root),
            "--destination",
            str(destination_root),
            "--transfer-id",
            "transfer-filetype-cli",
            "--policy-id",
            "policy-filetype-cli",
            "--file-type",
            "payload.bin=PE32FileType",
            "--file-type-action",
            "windows_executables=block",
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["outcomes"][0]["state"] == "blocked"
    assert report["outcomes"][0]["decision"]["file_type"] == "PE32FileType"
    assert report["outcomes"][0]["decision"]["reason"] == "file_type_rule:PE32FileType"
    assert not (destination_root / "payload.bin").exists()


def test_cli_migrate_warns_when_source_has_no_files(tmp_path: Path) -> None:
    source_root = tmp_path / "empty-source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()

    result = runner.invoke(
        app,
        [
            "migrate",
            "--source",
            str(source_root),
            "--destination",
            str(destination_root),
            "--transfer-id",
            "empty-transfer",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "transfer plan contains no files" in result.output
    assert json.loads(result.output.splitlines()[-1])["outcomes"] == []


def test_cli_serve_command_is_registered() -> None:
    result = runner.invoke(app, ["serve", "--help"])

    assert result.exit_code == 0, result.output
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--policy-id" in result.output
    assert "--scanner-mode" in result.output
    assert "--dsxa-base-url" in result.output
    assert "Host path for SFTPGo" in result.output
    assert "--verdict" in result.output
    assert "--file-type-action" in result.output
    assert "--verdict-action" in result.output
    assert "allow_after_remove" in result.output
    assert "EICAR antivirus" in result.output


def test_cli_migrate_command_exposes_gcs_destination_options() -> None:
    result = runner.invoke(app, ["migrate", "--help"])

    assert result.exit_code == 0, result.output
    assert "--destination-kind" in result.output
    assert "gs://bucket/prefix" in result.output


def test_cli_infers_gcs_destination_uri() -> None:
    assert _resolve_destination_kind("gs://clean-bucket/archive", "auto") == "gcs"
    assert _destination_uri("gs://clean-bucket/archive/", "auto") == "gs://clean-bucket/archive"


def test_cli_serve_dsxa_mode_requires_base_url() -> None:
    result = runner.invoke(app, ["serve", "--scanner-mode", "dsxa"])

    assert result.exit_code != 0
    assert "--dsxa-base-url is required" in result.output


def test_dsxa_client_import_error_mentions_local_install(monkeypatch) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dsxa_sdk_py.client":
            raise ModuleNotFoundError("No module named 'dsxa_sdk_py'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    try:
        _async_dsxa_client_class()
    except typer.BadParameter as exc:
        assert "pip install -e ./dsxa_sdk_py" in str(exc)
        assert "PYTHONPATH=dsx_transfer:dsxa_sdk_py" in str(exc)
    else:
        raise AssertionError("expected DSXA SDK import failure")


def test_cli_serve_rejects_invalid_sftpgo_block_response() -> None:
    result = runner.invoke(app, ["serve", "--sftpgo-block-response", "invalid"])

    assert result.exit_code != 0
    assert "invalid SFTPGo block response" in result.output
