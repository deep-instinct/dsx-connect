from dsx_connect_ng.control_plane.config_models import (
    parse_integration_runtime_config,
    resolve_policy_runtime_config,
    resolve_remediation_capabilities,
)


def test_parse_integration_runtime_config_with_proxy_reader() -> None:
    config = parse_integration_runtime_config(
        {
            "reader": {
                "default_strategy": "proxy",
                "proxy": {
                    "base_url": "http://127.0.0.1:8620",
                    "connector_name": "filesystem-connector",
                    "auth_mode": "none",
                    "timeout_seconds": 15,
                },
            }
        }
    )

    assert config.reader is not None
    assert config.reader.default_strategy == "proxy"
    assert config.reader.proxy is not None
    assert config.reader.proxy.base_url == "http://127.0.0.1:8620"
    assert config.reader.proxy.connector_name == "filesystem-connector"
    assert config.reader.proxy.timeout_seconds == 15


def test_resolve_policy_runtime_config_merges_scope_overrides() -> None:
    config = resolve_policy_runtime_config(
        {
            "policy": {
                "policy_id": "integration-default",
                "auto_dianna_on_verdicts": ["malicious"],
                "wait_for_dianna_on_auto_request": True,
                "malicious_verdict": {
                    "action": "quarantine",
                    "quarantine_target": {
                        "prefix": "tenant-quarantine",
                        "collision_strategy": "suffix_random",
                        "suffix_length": 10,
                    },
                },
                "non_compliant_treatment": "treat_as_malicious",
                "result_delivery_policy": {
                    "scan": "malicious_only",
                    "remediation": "all_outcomes",
                    "dianna": "completed_only",
                },
                "delivery": {
                    "workflow_summary_targets": [{"connector": "integration-summary"}],
                },
            }
        },
        {
            "policy_id": "scope-override",
            "malicious_verdict": {
                "action": "delete",
            },
            "delivery": {
                "scan_targets": [{"connector": "scope-scan"}],
            },
            "content_preservation_mode_by_verdict": {
                "malicious": "cached",
            },
        },
    )

    assert config.policy_id == "scope-override"
    assert config.auto_dianna_on_verdicts == ["malicious"]
    assert config.wait_for_dianna_on_auto_request is True
    assert config.malicious_verdict is not None
    assert config.malicious_verdict.action == "delete"
    assert config.malicious_verdict.tag_on_quarantine is True
    assert config.non_compliant_treatment == "treat_as_malicious"
    assert config.delivery is not None
    assert config.delivery.scan_targets == [{"connector": "scope-scan"}]
    assert config.content_preservation_mode_by_verdict == {"malicious": "cached"}


def test_parse_policy_runtime_config_supports_quarantine_collision_strategy() -> None:
    config = resolve_policy_runtime_config(
        {
            "policy": {
                "malicious_verdict": {
                    "action": "quarantine",
                    "quarantine_target": {
                        "path": "tenant-quarantine",
                        "collision_strategy": "suffix_random",
                        "suffix_length": 10,
                        "preserve_relative_path": True,
                    },
                },
            }
        }
    )

    assert config.malicious_verdict is not None
    assert config.malicious_verdict.quarantine_target is not None
    assert config.malicious_verdict.quarantine_target.collision_strategy == "suffix_random"
    assert config.malicious_verdict.quarantine_target.suffix_length == 10
    assert config.malicious_verdict.quarantine_target.preserve_relative_path is True


def test_quarantine_target_defaults_to_not_preserving_relative_path() -> None:
    config = resolve_policy_runtime_config(
        {
            "policy": {
                "malicious_verdict": {
                    "action": "quarantine",
                    "quarantine_target": {
                        "path": "tenant-quarantine",
                    },
                },
            }
        }
    )

    assert config.malicious_verdict is not None
    assert config.malicious_verdict.quarantine_target is not None
    assert config.malicious_verdict.quarantine_target.preserve_relative_path is False


def test_parse_integration_runtime_config_with_remediation_capabilities() -> None:
    config = parse_integration_runtime_config(
        {
            "remediation": {
                "supports_delete": True,
                "supports_move": True,
                "supports_tag": True,
            }
        }
    )

    assert config.remediation is not None
    assert config.remediation.supports_delete is True
    assert config.remediation.supports_movetag is False
    assert config.remediation.supports_action("movetag") is True


def test_resolve_remediation_capabilities_defaults_from_legacy_flag() -> None:
    capabilities = resolve_remediation_capabilities({}, default_enabled=True)

    assert capabilities.supports_delete is True
    assert capabilities.supports_move is True
    assert capabilities.supports_tag is True
    assert capabilities.supports_movetag is True
