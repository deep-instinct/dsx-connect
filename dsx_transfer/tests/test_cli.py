from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dsx_transfer.cli import app


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
    assert [outcome["state"] for outcome in report["outcomes"]] == ["blocked", "allowed"]
    assert not (destination_root / "bad.exe").exists()
    assert (destination_root / "clean.txt").read_bytes() == b"clean"
    assert [event["state"] for event in load_jsonl(audit_path)] == ["blocked", "allowed"]


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


def test_cli_serve_dsxa_mode_requires_base_url() -> None:
    result = runner.invoke(app, ["serve", "--scanner-mode", "dsxa"])

    assert result.exit_code != 0
    assert "--dsxa-base-url is required" in result.output


def test_cli_serve_rejects_invalid_sftpgo_block_response() -> None:
    result = runner.invoke(app, ["serve", "--sftpgo-block-response", "invalid"])

    assert result.exit_code != 0
    assert "invalid SFTPGo block response" in result.output
