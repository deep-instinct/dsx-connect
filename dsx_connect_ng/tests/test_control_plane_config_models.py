from dsx_connect_ng.control_plane.config_models import parse_integration_runtime_config, resolve_policy_runtime_config


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
    assert config.delivery is not None
    assert config.delivery.scan_targets == [{"connector": "scope-scan"}]
    assert config.content_preservation_mode_by_verdict == {"malicious": "cached"}
