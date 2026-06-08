from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_gcs_remediation_e2e_script_is_importable_from_repo_root() -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")
    assert module.__name__ == "scripts.validate_ng_gcs_remediation_e2e"


def test_parse_asset_supports_bucket_only_and_bucket_prefix() -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")

    assert module.parse_asset("bucket-a") == ("bucket-a", "")
    assert module.parse_asset("bucket-a/prefix/root") == ("bucket-a", "prefix/root")


def test_join_key_ignores_empty_segments() -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")

    assert module.join_key("prefix", "", "/scan/", "eicar.txt") == "prefix/scan/eicar.txt"


def test_resolve_env_file_prefers_existing_candidate_with_asset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")
    candidate_without_asset = tmp_path / "one.env"
    candidate_with_asset = tmp_path / "two.env"
    candidate_without_asset.write_text("DSXCONNECTOR_ASSET=\n", encoding="utf-8")
    candidate_with_asset.write_text("DSXCONNECTOR_ASSET=bucket-a\n", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "default_env_file_candidates",
        lambda: [candidate_without_asset, candidate_with_asset],
    )

    assert module.resolve_env_file(None) == candidate_with_asset


def test_resolve_credentials_path_uses_env_file_directory(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")
    env_file = tmp_path / ".env.local"
    env_file.write_text("", encoding="utf-8")

    resolved = module.resolve_credentials_path("gcp-sa.json", env_file=env_file)

    assert resolved == str((tmp_path / "gcp-sa.json").resolve())


def test_derive_quarantined_key_uses_requested_destination_filename() -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")

    item = {
        "remediation_stage": {
            "result": {
                "targetPath": "ng-e2e/quarantine",
                "details": {
                    "requestedAction": {
                        "destination": {
                            "path": "ng-e2e/quarantine",
                            "filename": "eicar.txt_9099f2a754",
                        },
                        "details": {
                            "quarantine_target": {
                                "preserve_relative_path": True,
                            }
                        },
                    }
                },
            }
        }
    }

    key = module.derive_quarantined_key(
        item=item,
        source_key="ng-e2e/scan/eicar.txt",
        fallback_quarantine_prefix="ng-e2e/quarantine",
    )

    assert key == "ng-e2e/quarantine/ng-e2e/scan/eicar.txt_9099f2a754"


def test_build_scope_policy_disables_relative_path_preservation() -> None:
    module = importlib.import_module("scripts.validate_ng_gcs_remediation_e2e")

    policy = module.build_scope_policy(
        quarantine_prefix="ng-e2e/quarantine",
        tag_on_quarantine=True,
    )

    target = policy["malicious_verdict"]["quarantine_target"]
    assert target["path"] == "ng-e2e/quarantine"
    assert target["preserve_relative_path"] is False
