from pathlib import Path

from dsx_connect_ng.local.dsx_connect_ng_local import (
    _default_env_template,
    _read_env_file,
    _select_service_specs,
    _service_specs,
)


def test_default_env_template_mentions_rabbitmq_mode() -> None:
    content = _default_env_template()
    assert "DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=postgres" in content
    assert "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq" in content
    assert "DSX_CONNECT_NG_RABBITMQ__URL=amqp://dsx:dsx@127.0.0.1:5672/%2F" in content
    assert "DSX_CONNECT_NG_POSTGRES__URL=postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_ng" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT=1" in content
    assert "DSX_CONNECT_NG_RESULT_SINK__BACKEND=stdout" in content


def test_read_env_file_parses_key_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("A=1\n# comment\nB=two\n")
    parsed = _read_env_file(env_file)
    assert parsed == {"A": "1", "B": "two"}


def test_service_specs_include_api_relay_scan_policy_remediation_delivery_and_dianna(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n")
    specs = _service_specs(tmp_path)
    assert [spec.name for spec in specs] == [
        "api",
        "relay",
        "scan-worker",
        "policy-worker",
        "remediation-worker",
        "result-sink-worker",
        "dianna-worker",
    ]
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")
    assert scan_spec.command[-2:] == ["--prefetch-count", "1"]


def test_select_service_specs_filters_requested_services(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n")
    specs = _service_specs(tmp_path)
    selected = _select_service_specs(specs, ["api", "scan-worker"])
    assert [spec.name for spec in selected] == ["api", "scan-worker"]


def test_select_service_specs_accepts_legacy_delivery_worker_alias(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n")
    specs = _service_specs(tmp_path)
    selected = _select_service_specs(specs, ["delivery-worker"])
    assert [spec.name for spec in selected] == ["result-sink-worker"]
