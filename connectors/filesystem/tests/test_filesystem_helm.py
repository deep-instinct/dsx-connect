from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


HELM = shutil.which("helm")


def _chart_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "deploy" / "helm"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _helm_template(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if HELM is None:
        pytest.skip("helm is not installed")
    return subprocess.run(
        [HELM, "template", "filesystem", str(_chart_dir()), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def test_dsx_connect_2_example_renders_scan_volume_and_registration_env() -> None:
    values = _repo_root() / "docs" / "dsx-connect-2" / "deployment" / "examples" / "filesystem-connector-values.yaml"
    rendered = _helm_template("-f", str(values)).stdout

    assert "name: scan-data" in rendered
    assert 'path: "/var/dsx-connect-2-test"' in rendered
    assert 'mountPath: "/app/scan_folder"' in rendered
    assert 'name: DSXCONNECTOR_ASSET' in rendered
    assert 'value: "/app/scan_folder"' in rendered
    assert 'name: DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE' in rendered
    assert 'name: DSXCONNECTOR_NG_PLATFORM' in rendered
    assert 'value: "filesystem"' in rendered
    assert 'name: DSXCONNECTOR_DSX_CONNECT_NG_URL' in rendered
    assert 'value: "http://dsx-connect-api:8091"' in rendered


def test_chart_lab_example_renders_scan_volume_and_registration_env() -> None:
    values = _chart_dir() / "examples" / "values-lab.example.yaml"
    rendered = _helm_template("-f", str(values)).stdout

    assert "name: scan-data" in rendered
    assert 'path: "/var/dsx-connect-2-test"' in rendered
    assert 'mountPath: "/app/scan_folder"' in rendered
    assert 'name: DSXCONNECTOR_ASSET' in rendered
    assert 'value: "/app/scan_folder"' in rendered
    assert 'name: DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE' in rendered
    assert 'name: DSXCONNECTOR_NG_PLATFORM' in rendered
    assert 'value: "filesystem"' in rendered
    assert 'name: DSXCONNECTOR_DSX_CONNECT_NG_URL' in rendered
    assert 'value: "http://dsx-connect-api:8091"' in rendered


def test_existing_claim_and_quarantine_volume_render() -> None:
    rendered = _helm_template(
        "--set",
        "scanVolume.enabled=true",
        "--set",
        "scanVolume.existingClaim=scan-pvc",
        "--set",
        "quarantineVolume.enabled=true",
        "--set",
        "quarantineVolume.existingClaim=quarantine-pvc",
        "--set",
        "quarantineVolume.subPath=quarantine-root",
        "--set-string",
        "env.DSXCONNECTOR_ITEM_ACTION=move",
    ).stdout

    assert "claimName: \"scan-pvc\"" in rendered
    assert "claimName: \"quarantine-pvc\"" in rendered
    assert "name: quarantine-dir" in rendered
    assert 'mountPath: "/app/quarantine"' in rendered
    assert 'subPath: "quarantine-root"' in rendered
    assert 'name: DSXCONNECTOR_ITEM_ACTION' in rendered
    assert 'value: "move"' in rendered
    assert 'name: DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO' in rendered
    assert 'value: "/app/quarantine"' in rendered


def test_scan_volume_requires_claim_or_host_path() -> None:
    result = _helm_template("--set", "scanVolume.enabled=true", check=False)

    assert result.returncode != 0
    assert "scanVolume.enabled=true requires either scanVolume.existingClaim or scanVolume.hostPath" in result.stderr


def test_scan_volume_rejects_claim_and_host_path_together() -> None:
    result = _helm_template(
        "--set",
        "scanVolume.enabled=true",
        "--set",
        "scanVolume.existingClaim=scan-pvc",
        "--set",
        "scanVolume.hostPath=/var/scan",
        check=False,
    )

    assert result.returncode != 0
    assert "set only one of scanVolume.existingClaim or scanVolume.hostPath" in result.stderr
