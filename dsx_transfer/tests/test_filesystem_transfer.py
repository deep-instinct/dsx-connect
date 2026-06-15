from __future__ import annotations

import asyncio
from pathlib import Path

from dsx_transfer.adapters import FilesystemSinkAdapter, FilesystemSourceAdapter
from dsx_transfer.engine import TransferEngine
from dsx_transfer.scan_gates import StaticVerdictScanGate


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_filesystem_source_builds_transfer_plan(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_file(source_root / "a.txt", b"alpha")
    write_file(source_root / "nested" / "b.txt", b"bravo")

    source = FilesystemSourceAdapter(source_root)
    plan = asyncio.run(
        source.plan(
            destination_uri="file:///tmp/destination",
            transfer_id="transfer-1",
            policy_id="policy-1",
        )
    )

    assert plan.transfer_id == "transfer-1"
    assert plan.policy_id == "policy-1"
    assert [item.object_identity for item in plan.items] == ["a.txt", "nested/b.txt"]
    assert [item.size_bytes for item in plan.items] == [5, 5]
    assert plan.items[0].destination_uri == "file:///tmp/destination/a.txt"


def test_empty_filesystem_source_builds_empty_transfer_plan(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    source = FilesystemSourceAdapter(source_root)
    plan = asyncio.run(
        source.plan(
            destination_uri="gs://clean-bucket/archive",
            transfer_id="transfer-empty",
        )
    )

    assert plan.items == []


def test_transfer_engine_allows_benign_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    write_file(source_root / "a.txt", b"alpha")
    write_file(source_root / "nested" / "b.txt", b"bravo")

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root, chunk_size=2),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(default_verdict="benign", policy_id="policy-allow"),
    )

    report = asyncio.run(
        engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-allow",
            policy_id="policy-allow",
        )
    )

    assert report.allowed_count == 2
    assert report.planned_count == 2
    assert report.blocked_count == 0
    assert report.failed_count == 0
    assert (destination_root / "a.txt").read_bytes() == b"alpha"
    assert (destination_root / "nested" / "b.txt").read_bytes() == b"bravo"
    assert [outcome.bytes_written for outcome in report.outcomes] == [5, 5]
    assert all(outcome.decision and outcome.decision.verdict == "benign" for outcome in report.outcomes)


def test_transfer_engine_blocks_malicious_files_before_destination_write(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    write_file(source_root / "clean.txt", b"clean")
    write_file(source_root / "bad.exe", b"malware")

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(
            default_verdict="benign",
            verdicts_by_identity={"bad.exe": "malicious"},
            policy_id="policy-block-malicious",
        ),
    )

    report = asyncio.run(
        engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-block",
            policy_id="policy-block-malicious",
        )
    )

    outcomes = {outcome.item.object_identity: outcome for outcome in report.outcomes}
    assert report.allowed_count == 1
    assert report.blocked_count == 1
    assert report.failed_count == 0
    assert (destination_root / "clean.txt").read_bytes() == b"clean"
    assert not (destination_root / "bad.exe").exists()
    assert outcomes["bad.exe"].state == "blocked"
    assert outcomes["bad.exe"].decision is not None
    assert outcomes["bad.exe"].decision.verdict == "malicious"
    assert outcomes["bad.exe"].decision.action == "block"
