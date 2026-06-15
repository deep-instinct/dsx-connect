from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dsx_transfer.contracts import ObjectRef
from dsx_transfer.adapters import FilesystemSourceAdapter, GcsSinkAdapter, parse_gcs_uri
import dsx_transfer.adapters.gcs as gcs_adapter
from dsx_transfer.engine import TransferEngine
from dsx_transfer.scan_gates import StaticVerdictScanGate


class FakeObjectWriter:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.validated_buckets: list[str] = []

    def validate(self, *, bucket: str | None = None) -> None:
        if bucket is not None:
            self.validated_buckets.append(bucket)

    async def write_object(self, ref: ObjectRef, chunks) -> int:
        data = b""
        async for chunk in chunks:
            data += chunk
        self.objects[(ref.bucket, ref.key)] = data
        return len(data)


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_parse_gcs_uri() -> None:
    parsed = parse_gcs_uri("gs://clean-bucket/archive/prefix/")

    assert parsed.bucket == "clean-bucket"
    assert parsed.prefix == "archive/prefix"
    assert parsed.uri == "gs://clean-bucket/archive/prefix"


@pytest.mark.parametrize("uri", ["bucket/path", "gs://"])
def test_parse_gcs_uri_rejects_invalid_uri(uri: str) -> None:
    with pytest.raises(ValueError):
        parse_gcs_uri(uri)


def test_gcs_sink_creates_default_writer_at_construction(monkeypatch) -> None:
    def missing_credentials(*, client=None):
        raise RuntimeError("missing adc")

    monkeypatch.setattr(gcs_adapter, "_default_gcs_writer", missing_credentials)

    with pytest.raises(RuntimeError, match="missing adc"):
        GcsSinkAdapter("gs://clean-bucket/archive")


def test_gcs_sink_validates_writer_at_construction() -> None:
    writer = FakeObjectWriter()

    GcsSinkAdapter("gs://clean-bucket/archive", writer=writer)

    assert writer.validated_buckets == ["clean-bucket"]


def test_gcs_sink_wraps_writer_validation_failure() -> None:
    class FailingWriter(FakeObjectWriter):
        def validate(self, *, bucket: str | None = None) -> None:
            raise RuntimeError("no bucket access")

    with pytest.raises(RuntimeError, match="bucket access"):
        GcsSinkAdapter("gs://clean-bucket/archive", writer=FailingWriter())


def test_filesystem_to_gcs_transfer_writes_allowed_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_file(source_root / "a.txt", b"alpha")
    write_file(source_root / "nested" / "b.txt", b"bravo")
    writer = FakeObjectWriter()

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root, chunk_size=2),
        sink=GcsSinkAdapter("gs://clean-bucket/archive", writer=writer),
        scan_gate=StaticVerdictScanGate(default_verdict="benign", policy_id="policy-allow"),
    )

    report = asyncio.run(
        engine.run(
            destination_uri="gs://clean-bucket/archive",
            transfer_id="transfer-gcs",
            policy_id="policy-allow",
        )
    )

    assert report.allowed_count == 2
    assert report.failed_count == 0
    assert writer.objects[("clean-bucket", "archive/a.txt")] == b"alpha"
    assert writer.objects[("clean-bucket", "archive/nested/b.txt")] == b"bravo"


def test_filesystem_to_gcs_blocks_before_upload(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_file(source_root / "clean.txt", b"clean")
    write_file(source_root / "bad.exe", b"malware")
    writer = FakeObjectWriter()

    engine = TransferEngine(
        source=FilesystemSourceAdapter(source_root),
        sink=GcsSinkAdapter("gs://clean-bucket", writer=writer),
        scan_gate=StaticVerdictScanGate(
            default_verdict="benign",
            verdicts_by_identity={"bad.exe": "malicious"},
            policy_id="policy-block",
        ),
    )

    report = asyncio.run(
        engine.run(
            destination_uri="gs://clean-bucket",
            transfer_id="transfer-gcs-block",
            policy_id="policy-block",
        )
    )

    assert report.allowed_count == 1
    assert report.blocked_count == 1
    assert writer.objects[("clean-bucket", "clean.txt")] == b"clean"
    assert ("clean-bucket", "bad.exe") not in writer.objects
