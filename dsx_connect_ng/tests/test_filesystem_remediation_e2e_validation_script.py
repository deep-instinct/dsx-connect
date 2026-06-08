from __future__ import annotations

import importlib
from pathlib import Path
import pytest


def test_filesystem_remediation_e2e_script_is_importable_from_repo_root() -> None:
    module = importlib.import_module("scripts.validate_ng_filesystem_remediation_e2e")
    assert module.__name__ == "scripts.validate_ng_filesystem_remediation_e2e"


def test_build_scope_policy_uses_quarantine_target(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_filesystem_remediation_e2e")

    policy = module.build_scope_policy(
        quarantine_dir=tmp_path / "quarantine",
        tag_on_quarantine=True,
    )

    assert policy == {
        "malicious_verdict": {
            "action": "quarantine",
            "quarantine_target": {
                "path": str(tmp_path / "quarantine"),
                "preserve_relative_path": False,
            },
            "tag_on_quarantine": True,
        }
    }


def test_expected_tag_sidecar_path_appends_sidecar_suffix(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_filesystem_remediation_e2e")

    sidecar = module.expected_tag_sidecar_path(tmp_path / "eicar.txt")

    assert sidecar == tmp_path / "eicar.txt.dsx.tags.json"


def test_expected_quarantine_path_uses_requested_filename(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_filesystem_remediation_e2e")

    item = {
        "remediation_stage": {
            "result": {
                "targetPath": str(tmp_path / "quarantine"),
                "details": {
                    "requestedAction": {
                        "destination": {
                            "path": str(tmp_path / "quarantine"),
                            "filename": "eicar.txt_dcea03a894",
                        }
                    }
                },
            }
        }
    }

    expected = module.expected_quarantine_path(
        item=item,
        quarantine_dir=tmp_path / "quarantine",
        sample_name="eicar.txt",
    )

    assert expected == tmp_path / "quarantine" / "eicar.txt_dcea03a894"


def test_default_filesystem_state_root_prefers_2g(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_filesystem_remediation_e2e")

    local_root = tmp_path / ".dsx-connect-local"
    legacy = local_root / "filesystem-connector" / "data"
    two_g = local_root / "filesystem-connector-2g" / "data"
    legacy.mkdir(parents=True)
    two_g.mkdir(parents=True)

    monkeypatch.setattr(module.Path, "home", staticmethod(lambda: tmp_path))

    assert module.default_filesystem_state_root() == two_g
