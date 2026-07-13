from __future__ import annotations

from pathlib import Path


def test_ng_image_installs_dsxa_sdk_for_dsxa_scanner_mode() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "COPY dsxa_sdk_py/ dsxa_sdk_py/" in text
    assert '-e "./dsxa_sdk_py"' in text
