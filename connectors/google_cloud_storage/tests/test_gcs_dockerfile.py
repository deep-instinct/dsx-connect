from __future__ import annotations

from pathlib import Path


def test_gcs_image_copies_full_connector_package() -> None:
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "COPY connectors/google_cloud_storage/*.py connectors/google_cloud_storage/" in text
    assert "COPY connectors/google_cloud_storage/gcs_client.py" not in text
