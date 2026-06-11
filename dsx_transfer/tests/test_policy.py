from __future__ import annotations

import asyncio
from pathlib import Path

from dsx_transfer.adapters import FilesystemSinkAdapter, FilesystemSourceAdapter
from dsx_transfer.dsxa_file_types import expand_file_type_actions
from dsx_transfer.engine import TransferEngine
from dsx_transfer.models import ScanObservation, TransferItem
from dsx_transfer.policy import GuardedTransferPolicy
from dsx_transfer.scan_gates import StaticVerdictScanGate


EICAR_TEST_FILE = b"".join(
    [
        b"X5O!P%@AP[4",
        b"\\PZX54(P^)7CC)7}$",
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
        b"!$H+H*",
    ]
)


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_policy_file_type_rule_overrides_benign_verdict() -> None:
    policy = GuardedTransferPolicy(
        policy_id="policy-filetype",
        file_type_actions={"PE32FileType": "block"},
    )

    decision = policy.evaluate(
        item=TransferItem(
            source_uri="file:///source/report.bin",
            destination_uri="file:///dest/report.bin",
            object_identity="report.bin",
        ),
        observation=ScanObservation(verdict="benign", file_type="PE32FileType"),
    )

    assert decision.verdict == "benign"
    assert decision.file_type == "PE32FileType"
    assert decision.action == "block"
    assert decision.reason == "file_type_rule:PE32FileType"


def test_file_type_group_expands_to_dsxa_file_types() -> None:
    expanded = expand_file_type_actions({"windows_executables": "block"})

    assert expanded["PEFileType"] == "block"
    assert expanded["PE32FileType"] == "block"
    assert expanded["PE64FileType"] == "block"


def test_engine_excludes_detected_file_type_without_destination_write(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    write_file(source_root / "archive.dat", b"archive")

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(
            default_verdict="benign",
            file_types_by_identity={"archive.dat": "OOXMLFileType"},
            file_type_actions={"OOXMLFileType": "exclude"},
            policy_id="policy-exclude-archives",
        ),
    )

    report = asyncio.run(
        engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-exclude",
            policy_id="policy-exclude-archives",
        )
    )

    assert report.allowed_count == 0
    assert report.excluded_count == 1
    assert not (destination_root / "archive.dat").exists()
    outcome = report.outcomes[0]
    assert outcome.state == "excluded"
    assert outcome.decision is not None
    assert outcome.decision.action == "exclude"
    assert outcome.decision.file_type == "OOXMLFileType"


def test_static_scan_gate_can_detect_eicar_test_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    write_file(source_root / "eicar.txt", EICAR_TEST_FILE)

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=FilesystemSinkAdapter(destination_root),
        scan_gate=StaticVerdictScanGate(
            policy_id="policy-eicar-demo",
            detect_eicar_test_file=True,
        ),
    )

    report = asyncio.run(
        engine.run(
            destination_uri=destination_root.as_uri(),
            transfer_id="transfer-eicar-demo",
            policy_id="policy-eicar-demo",
        )
    )

    assert report.blocked_count == 1
    assert not (destination_root / "eicar.txt").exists()
    decision = report.outcomes[0].decision
    assert decision is not None
    assert decision.verdict == "malicious"
    assert decision.action == "block"
    assert decision.reason == "verdict_rule:malicious"
    assert decision.details["demo_eicar_test_file_detected"] is True
