from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dsx_transfer.adapters import FilesystemSinkAdapter, FilesystemSourceAdapter
from dsx_transfer.audit import JsonLinesAuditSink
from dsx_transfer.checkpoint import JsonCheckpointStore
from dsx_transfer.engine import TransferEngine
from dsx_transfer.scan_gates import StaticVerdictScanGate


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_transfer_engine_emits_jsonl_audit_events(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    audit_path = tmp_path / "audit.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    write_file(source_root / "clean.txt", b"clean")
    write_file(source_root / "bad.exe", b"malware")

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(
            default_verdict="benign",
            verdicts_by_identity={"bad.exe": "malicious"},
            policy_id="policy-audit",
        ),
        audit_sink=JsonLinesAuditSink(audit_path),
        checkpoint_store=JsonCheckpointStore(checkpoint_path),
    )

    report = asyncio.run(
        engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-audit",
            policy_id="policy-audit",
        )
    )

    assert report.allowed_count == 1
    assert report.blocked_count == 1
    events = load_jsonl(audit_path)
    assert [event["object_identity"] for event in events] == ["bad.exe", "clean.txt"]
    assert [event["state"] for event in events] == ["blocked", "allowed"]
    assert events[0]["verdict"] == "malicious"
    assert events[1]["bytes_written"] == 5


def test_checkpoint_store_skips_already_allowed_items_on_rerun(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    audit_path = tmp_path / "audit.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    write_file(source_root / "clean.txt", b"clean")

    first_engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(default_verdict="benign", policy_id="policy-resume"),
        audit_sink=JsonLinesAuditSink(audit_path),
        checkpoint_store=JsonCheckpointStore(checkpoint_path),
    )
    first_report = asyncio.run(
        first_engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-resume",
            policy_id="policy-resume",
        )
    )
    assert first_report.allowed_count == 1
    assert (destination_root / "clean.txt").read_bytes() == b"clean"

    (destination_root / "clean.txt").write_bytes(b"already-present")
    second_engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(default_verdict="malicious", policy_id="policy-resume"),
        audit_sink=JsonLinesAuditSink(audit_path),
        checkpoint_store=JsonCheckpointStore(checkpoint_path),
    )
    second_report = asyncio.run(
        second_engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-resume",
            policy_id="policy-resume",
        )
    )

    assert second_report.skipped_count == 1
    assert second_report.allowed_count == 0
    assert second_report.blocked_count == 0
    assert (destination_root / "clean.txt").read_bytes() == b"already-present"
    events = load_jsonl(audit_path)
    assert [event["state"] for event in events] == ["allowed", "skipped"]
