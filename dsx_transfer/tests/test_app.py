from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from fastapi.testclient import TestClient

from dsx_transfer.app import create_app
from dsx_transfer.audit import JsonLinesAuditSink
from dsx_transfer.contracts import ScanGate
from dsx_transfer.dsxa_scan_gate import DsxaStreamScanGate
from dsx_transfer.models import ScanDecision, TransferItem
from dsx_transfer.scan_gates import StaticVerdictScanGate


EICAR_TEST_FILE = b"".join(
    [
        b"X5O!P%@AP[4",
        b"\\PZX54(P^)7CC)7}$",
        b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
        b"!$H+H*",
    ]
)


class RecordingScanGate(ScanGate):
    def __init__(self) -> None:
        self.item: TransferItem | None = None
        self.bytes_scanned = 0

    async def decide(self, item: TransferItem, chunks: AsyncIterator[bytes]) -> ScanDecision:
        self.item = item
        self.bytes_scanned = 0
        async for chunk in chunks:
            self.bytes_scanned += len(chunk)
        return ScanDecision(
            verdict="benign",
            action="allow",
            file_type="PDFFileType",
            policy_id="default-transfer-policy",
            scan_guid="scan-123",
            reason="verdict_rule:benign",
        )


class NeverCalledDsxaClient:
    async def scan_binary_stream(self, chunks: AsyncIterator[bytes], **kwargs):
        raise AssertionError("pre-upload hook must not scan an empty stream")


def test_healthz() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sftpgo_pre_upload_returns_commit_decision() -> None:
    scan_gate = RecordingScanGate()
    client = TestClient(create_app(scan_gate=scan_gate))

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={
            "event": {
                "virtual_path": "/inbox/report.pdf",
                "username": "alice",
                "connection_id": "conn-1",
                "protocol": "sftp",
            },
            "content_text": "hello",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "allow"
    assert body["verdict"] == "benign"
    assert body["file_type"] == "PDFFileType"
    assert body["policy_id"] == "default-transfer-policy"
    assert body["details"]["transfer_platform"] == "sftpgo"
    assert body["details"]["transfer_platform_event_type"] == "pre-upload"
    assert scan_gate.item is not None
    assert scan_gate.item.object_identity == "/inbox/report.pdf"
    assert scan_gate.item.metadata["protocol"] == "sftp"
    assert scan_gate.bytes_scanned == 5


def test_sftpgo_pre_upload_accepts_base64_content() -> None:
    scan_gate = RecordingScanGate()
    client = TestClient(create_app(scan_gate=scan_gate))

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={
            "event": {"path": "/inbox/report.pdf"},
            "content_base64": "aGVsbG8=",
        },
    )

    assert response.status_code == 200
    assert scan_gate.bytes_scanned == 5


def test_sftpgo_pre_upload_blocks_static_malicious_verdict() -> None:
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                verdicts_by_identity={"/inbox/bad.exe": "malicious"},
                policy_id="block-malicious",
            )
        )
    )

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={
            "event": {"path": "/inbox/bad.exe"},
            "content_text": "malware",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "block"
    assert body["verdict"] == "malicious"
    assert body["policy_id"] == "block-malicious"
    assert body["reason"] == "verdict_rule:malicious"


def test_sftpgo_pre_upload_blocks_static_file_type_rule() -> None:
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                file_types_by_identity={"/inbox/payload.bin": "PE32FileType"},
                file_type_actions={"windows_executables": "block"},
                policy_id="block-executables",
            )
        )
    )

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={
            "event": {"path": "/inbox/payload.bin"},
            "content_text": "payload",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "block"
    assert body["verdict"] == "benign"
    assert body["file_type"] == "PE32FileType"
    assert body["policy_id"] == "block-executables"
    assert body["reason"] == "file_type_rule:PE32FileType"


def test_sftpgo_hook_returns_200_for_allow() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/sftpgo/hooks/pre-upload",
        json={
            "action": "pre-upload",
            "virtual_path": "/inbox/clean.txt",
            "username": "alice",
            "protocol": "SFTP",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "allow"


def test_sftpgo_hook_returns_403_for_block() -> None:
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                verdicts_by_identity={"/inbox/bad.exe": "malicious"},
                policy_id="block-malicious",
            )
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/pre-upload",
        json={
            "action": "pre-upload",
            "virtual_path": "/inbox/bad.exe",
            "username": "alice",
            "protocol": "SFTP",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["action"] == "block"
    assert response.json()["detail"]["reason"] == "verdict_rule:malicious"


def test_sftpgo_hook_rejects_dsxa_without_content_bytes() -> None:
    client = TestClient(create_app(scan_gate=DsxaStreamScanGate(NeverCalledDsxaClient())))

    response = client.post(
        "/api/v1/sftpgo/hooks/pre-upload",
        json={
            "action": "pre-upload",
            "virtual_path": "/inbox/file.txt",
            "username": "alice",
        },
    )

    assert response.status_code == 409
    assert "do not include file bytes" in response.json()["detail"]


def test_sftpgo_upload_hook_reads_uploaded_file(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "clean.txt"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"clean")
    scan_gate = RecordingScanGate()
    client = TestClient(create_app(scan_gate=scan_gate, sftpgo_storage_root=storage_root))

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/clean.txt",
            "fs_path": "/srv/sftpgo/data/demo/clean.txt",
            "username": "demo",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "allow"
    assert scan_gate.bytes_scanned == 5
    assert uploaded.exists()


def test_sftpgo_upload_hook_emits_audit_event(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "clean.txt"
    audit_path = tmp_path / "audit.jsonl"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"clean")
    client = TestClient(
        create_app(
            scan_gate=RecordingScanGate(),
            audit_sink=JsonLinesAuditSink(audit_path),
            sftpgo_storage_root=storage_root,
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/clean.txt",
            "fs_path": "/srv/sftpgo/data/demo/clean.txt",
            "username": "demo",
            "session_id": "session-1",
        },
    )

    assert response.status_code == 200
    event = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert event["event_type"] == "transfer_platform_decision"
    assert event["transfer_id"] == "session-1"
    assert event["object_identity"] == "/clean.txt"
    assert event["state"] == "allowed"
    assert event["action"] == "allow"
    assert event["transfer_platform"] == "sftpgo"
    assert event["platform_event_type"] == "upload"
    assert event["user_id"] == "demo"
    assert event["bytes_written"] == 5


def test_sftpgo_upload_hook_resolves_sftpgo_path_field(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "clean.txt"
    storage_root.mkdir()
    uploaded.write_bytes(b"clean")
    scan_gate = RecordingScanGate()
    client = TestClient(
        create_app(
            scan_gate=scan_gate,
            sftpgo_storage_root=storage_root,
            sftpgo_container_root="/srv/sftpgo",
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/clean.txt",
            "path": "/srv/sftpgo/clean.txt",
            "username": "demo",
        },
    )

    assert response.status_code == 200
    assert scan_gate.bytes_scanned == 5


def test_sftpgo_upload_hook_removes_blocked_file(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "bad.exe"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"malware")
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                verdicts_by_identity={"/bad.exe": "malicious",
                },
                policy_id="block-malicious",
            ),
            sftpgo_storage_root=storage_root,
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/bad.exe",
            "fs_path": "/srv/sftpgo/data/demo/bad.exe",
            "username": "demo",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["action"] == "block"
    assert not uploaded.exists()


def test_sftpgo_upload_hook_can_allow_after_removing_blocked_file(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "bad.exe"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"malware")
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                verdicts_by_identity={"/bad.exe": "malicious"},
                policy_id="block-malicious",
            ),
            sftpgo_storage_root=storage_root,
            sftpgo_block_response="allow_after_remove",
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/bad.exe",
            "fs_path": "/srv/sftpgo/data/demo/bad.exe",
            "username": "demo",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "block"
    assert response.json()["reason"] == "verdict_rule:malicious"
    assert not uploaded.exists()


def test_sftpgo_upload_hook_emits_audit_event_before_blocking(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "bad.exe"
    audit_path = tmp_path / "audit.jsonl"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b"malware")
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                verdicts_by_identity={"/bad.exe": "malicious"},
                policy_id="block-malicious",
            ),
            audit_sink=JsonLinesAuditSink(audit_path),
            sftpgo_storage_root=storage_root,
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/bad.exe",
            "fs_path": "/srv/sftpgo/data/demo/bad.exe",
            "username": "demo",
        },
    )

    assert response.status_code == 403
    event = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert event["event_type"] == "transfer_platform_decision"
    assert event["object_identity"] == "/bad.exe"
    assert event["state"] == "blocked"
    assert event["verdict"] == "malicious"
    assert event["action"] == "block"
    assert event["policy_id"] == "block-malicious"
    assert event["bytes_written"] == 7
    assert not uploaded.exists()


def test_sftpgo_upload_hook_blocks_eicar_test_file_in_static_demo_mode(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    uploaded = storage_root / "demo" / "eicar.txt"
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(EICAR_TEST_FILE)
    client = TestClient(
        create_app(
            scan_gate=StaticVerdictScanGate(
                policy_id="sftpgo-upload-demo",
                detect_eicar_test_file=True,
            ),
            sftpgo_storage_root=storage_root,
        )
    )

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/eicar.txt",
            "fs_path": "/srv/sftpgo/data/demo/eicar.txt",
            "username": "demo",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["action"] == "block"
    assert response.json()["detail"]["verdict"] == "malicious"
    assert response.json()["detail"]["details"]["demo_eicar_test_file_detected"] is True
    assert not uploaded.exists()


def test_sftpgo_upload_hook_requires_storage_root() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/sftpgo/hooks/upload",
        json={
            "action": "upload",
            "virtual_path": "/clean.txt",
            "fs_path": "/srv/sftpgo/data/demo/clean.txt",
            "username": "demo",
        },
    )

    assert response.status_code == 400
    assert "--sftpgo-storage-root" in response.json()["detail"]


def test_sftpgo_pre_upload_rejects_missing_object_identity() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={"event": {"username": "alice"}},
    )

    assert response.status_code == 400
    assert "object identity" in response.json()["detail"]


def test_sftpgo_pre_upload_rejects_invalid_base64() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/transfer-decisions/sftpgo/pre-upload",
        json={
            "event": {"path": "/inbox/report.pdf"},
            "content_base64": "not base64",
        },
    )

    assert response.status_code == 400
    assert "content_base64" in response.json()["detail"]
