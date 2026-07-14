from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


HELM = shutil.which("helm")


def _chart_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "deploy" / "helm"


def _helm_template(*args: str) -> str:
    if HELM is None:
        pytest.skip("helm is not installed")
    result = subprocess.run(
        [HELM, "template", "gcs", str(_chart_dir()), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def test_gke_wif_values_render_service_account_without_json_credentials() -> None:
    rendered = _helm_template(
        "-f",
        str(_chart_dir() / "examples" / "values-gke-wif.example.yaml"),
    )

    assert "kind: ServiceAccount" in rendered
    assert 'serviceAccountName: "gcs-connector"' in rendered
    assert "iam.gke.io/gcp-service-account: dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" in rendered
    assert "DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE" in rendered
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in rendered
    assert "gcp-creds" not in rendered


def test_json_secret_values_still_render_credentials_mount() -> None:
    rendered = _helm_template("-f", str(_chart_dir() / "values-local-ng.yaml"))

    assert 'serviceAccountName: "default"' in rendered
    assert "gcp-creds" in rendered
    assert "secretName: \"gcp-sa\"" in rendered
    assert "GOOGLE_APPLICATION_CREDENTIALS" in rendered
