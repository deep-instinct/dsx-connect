from pathlib import Path

import pytest

from dsx_connect_ng.local.dsx_connect_ng_local import (
    _default_env_template,
    _docker_logs,
    _ensure_dsxa_container,
    _ensure_postgres_container,
    _ensure_rabbitmq_container,
    _read_env_file,
    _runtime_env_overrides,
    _select_service_specs,
    _service_specs,
    _wait_for_rabbitmq_ready,
)


def test_default_env_template_mentions_rabbitmq_mode() -> None:
    content = _default_env_template()
    assert "DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=postgres" in content
    assert "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq" in content
    assert "DSX_CONNECT_NG_RABBITMQ__URL=amqp://dsx:dsx@127.0.0.1:5672/%2F" in content
    assert "DSX_CONNECT_NG_POSTGRES__URL=postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_ng" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT=1000" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT=1" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE=100" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS=0.5" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY=6" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE=scanned" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS=true" in content
    assert "DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES=false" in content
    assert "DSX_CONNECT_NG_LOCAL__DSXA_IMAGE=" in content
    assert "APPLIANCE_URL=<your-appliance.deepinstinctweb.com>" in content
    assert "DSX_CONNECT_NG_LOCAL__POLICY_PREFETCH_COUNT=1" in content
    assert "DSX_CONNECT_NG_LOCAL__RESULT_SINK_PREFETCH_COUNT=1" in content
    assert "DSX_CONNECT_NG_RESULT_SINK__BACKEND=stdout" in content


def test_read_env_file_parses_key_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("A=1\n# comment\nB=two\n")
    parsed = _read_env_file(env_file)
    assert parsed == {"A": "1", "B": "two"}


def test_runtime_env_overrides_include_relay_tuning_options() -> None:
    class Ctx:
        obj = {
            "with_postgres_docker": False,
            "with_rabbit_docker": False,
            "scan_worker_prefetch_count": 10,
            "scan_worker_count": 3,
            "policy_worker_prefetch_count": 1,
            "result_sink_worker_prefetch_count": 1,
            "relay_max_active_scan_items": 30,
            "relay_batch_size": 50,
            "relay_poll_interval_seconds": 0.25,
        }

    overrides = _runtime_env_overrides(Ctx())

    assert overrides["DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT"] == "10"
    assert overrides["DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT"] == "3"
    assert overrides["DSX_CONNECT_NG_RELAY__MAX_ACTIVE_SCAN_ITEMS"] == "30"
    assert overrides["DSX_CONNECT_NG_RELAY__BATCH_SIZE"] == "50"
    assert overrides["DSX_CONNECT_NG_RELAY__POLL_INTERVAL_SECONDS"] == "0.25"


def test_runtime_env_overrides_use_short_postgres_relay_poll_by_default() -> None:
    class Ctx:
        obj = {
            "with_postgres_docker": True,
            "with_rabbit_docker": False,
            "scan_worker_prefetch_count": 10,
            "scan_worker_count": 3,
            "policy_worker_prefetch_count": 1,
            "result_sink_worker_prefetch_count": 1,
            "relay_max_active_scan_items": None,
            "relay_batch_size": None,
            "relay_poll_interval_seconds": None,
        }

    overrides = _runtime_env_overrides(Ctx())

    assert overrides["DSX_CONNECT_NG_RELAY__POLL_INTERVAL_SECONDS"] == "0.25"


def test_runtime_env_overrides_configure_local_dsxa_docker() -> None:
    class Ctx:
        obj = {
            "with_postgres_docker": False,
            "with_rabbit_docker": False,
            "with_dsxa_docker": True,
            "dsxa_host_port": 15000,
            "dsxa_scheme": "http",
            "dsxa_verify_tls": False,
            "dsxa_auth_token": "rest-token",
            "scan_worker_prefetch_count": 10,
            "scan_worker_count": 1,
            "policy_worker_prefetch_count": 1,
            "result_sink_worker_prefetch_count": 1,
            "relay_max_active_scan_items": None,
            "relay_batch_size": None,
            "relay_poll_interval_seconds": None,
        }

    overrides = _runtime_env_overrides(Ctx())

    assert overrides["DSX_CONNECT_NG_SCANNER__MODE"] == "dsxa"
    assert overrides["DSX_CONNECT_NG_SCANNER__BASE_URL"] == "http://127.0.0.1:15000"
    assert overrides["DSX_CONNECT_NG_SCANNER__VERIFY_TLS"] == "false"
    assert overrides["DSX_CONNECT_NG_SCANNER__AUTH_TOKEN"] == "rest-token"


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
    assert "--prefetch-count" in scan_spec.command
    assert scan_spec.command[scan_spec.command.index("--prefetch-count") + 1] == "1000"
    assert "--no-scan-only-runtime-leases" in scan_spec.command
    assert "--scan-only-runtime-leases" not in scan_spec.command
    assert scan_spec.command[scan_spec.command.index("--scanner-client-scope") + 1] == "shared"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-window-size") + 1] == "100"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-window-wait-seconds") + 1] == "0.5"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-concurrency") + 1] == "6"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-ack-mode") + 1] == "scanned"
    assert "--scan-batch-trust-items" in scan_spec.command
    assert "--no-scan-batch-trust-items" not in scan_spec.command
    policy_spec = next(spec for spec in specs if spec.name == "policy-worker")
    assert policy_spec.command[-2:] == ["--prefetch-count", "1"]
    result_sink_spec = next(spec for spec in specs if spec.name == "result-sink-worker")
    assert result_sink_spec.command[-2:] == ["--prefetch-count", "1"]


def test_service_specs_can_start_multiple_scan_worker_processes(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT=4\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT=3\n"
    )

    specs = _service_specs(tmp_path)
    scan_specs = [spec for spec in specs if spec.role == "scan-worker"]

    assert [spec.name for spec in scan_specs] == ["scan-worker-1", "scan-worker-2", "scan-worker-3"]
    assert [spec.logfile.name for spec in scan_specs] == [
        "scan-worker-1.log",
        "scan-worker-2.log",
        "scan-worker-3.log",
    ]
    assert all(spec.command[spec.command.index("--prefetch-count") + 1] == "4" for spec in scan_specs)


def test_service_specs_can_disable_scan_only_runtime_leases(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES=false\n"
    )

    specs = _service_specs(tmp_path)
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")

    assert "--no-scan-only-runtime-leases" in scan_spec.command
    assert "--scan-only-runtime-leases" not in scan_spec.command


def test_service_specs_can_use_per_task_scanner_client_scope(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCANNER_CLIENT_SCOPE=per-task\n"
    )

    specs = _service_specs(tmp_path)
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")

    assert scan_spec.command[scan_spec.command.index("--scanner-client-scope") + 1] == "per-task"


def test_service_specs_can_thread_scan_worker_service_io(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_WORKER_SERVICE_IO_THREADED=true\n"
    )

    specs = _service_specs(tmp_path)
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")

    assert "--service-io-threaded" in scan_spec.command
    assert "--no-service-io-threaded" not in scan_spec.command


def test_service_specs_can_configure_scan_batch_window(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE=8\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS=0.02\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY=8\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE=accepted\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS=true\n"
    )

    specs = _service_specs(tmp_path)
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")

    assert scan_spec.command[scan_spec.command.index("--scan-batch-window-size") + 1] == "8"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-window-wait-seconds") + 1] == "0.02"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-concurrency") + 1] == "8"
    assert scan_spec.command[scan_spec.command.index("--scan-batch-ack-mode") + 1] == "accepted"
    assert "--scan-batch-trust-items" in scan_spec.command
    assert "--no-scan-batch-trust-items" not in scan_spec.command


def test_service_specs_can_disable_scan_batch_trusted_items(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS=false\n"
    )

    specs = _service_specs(tmp_path)
    scan_spec = next(spec for spec in specs if spec.name == "scan-worker")

    assert "--no-scan-batch-trust-items" in scan_spec.command
    assert "--scan-batch-trust-items" not in scan_spec.command


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


def test_select_service_specs_selects_all_scan_worker_processes_by_role(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text(
        "DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq\n"
        "DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT=2\n"
    )
    specs = _service_specs(tmp_path)

    selected = _select_service_specs(specs, ["scan-worker"])

    assert [spec.name for spec in selected] == ["scan-worker-1", "scan-worker-2"]


def test_ensure_rabbitmq_container_does_not_use_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_docker_run(args: list[str]):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "container-id"
            stderr = ""

        if args[:2] == ["inspect", "-f"]:
            Result.returncode = 1
            Result.stdout = ""
            Result.stderr = "missing"
        return Result()

    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_run", fake_docker_run)

    _ensure_rabbitmq_container("rabbit")

    run_call = next(call for call in calls if call and call[0] == "run")
    assert "--rm" not in run_call


def test_ensure_postgres_container_does_not_use_rm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_docker_run(args: list[str]):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "container-id"
            stderr = ""

        if args[:2] == ["inspect", "-f"]:
            Result.returncode = 1
            Result.stdout = ""
            Result.stderr = "missing"
        return Result()

    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_run", fake_docker_run)

    _ensure_postgres_container("postgres")

    run_call = next(call for call in calls if call and call[0] == "run")
    assert "--rm" not in run_call


def test_ensure_dsxa_container_uses_configured_image_port_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_docker_run(args: list[str]):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "container-id"
            stderr = ""

        if args[:2] == ["inspect", "-f"]:
            Result.returncode = 1
            Result.stdout = ""
            Result.stderr = "missing"
        return Result()

    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_run", fake_docker_run)

    _ensure_dsxa_container(
        "dsxa",
        image="repo/dsxa:test",
        host_port=15000,
        container_port=5000,
        env_values={
            "APPLIANCE_URL": "tenant.example",
            "TOKEN": "scanner-token",
            "SCANNER_ID": "scanner-id",
            "FLAVOR": "rest,config",
            "NO_SSL": "true",
            "AUTH_TOKEN": "rest-token",
        },
    )

    run_call = next(call for call in calls if call and call[0] == "run")
    assert "--rm" not in run_call
    assert "repo/dsxa:test" == run_call[-1]
    assert ["-p", "15000:5000"] == run_call[run_call.index("-p") : run_call.index("-p") + 2]
    assert "APPLIANCE_URL=tenant.example" in run_call
    assert "TOKEN=scanner-token" in run_call
    assert "SCANNER_ID=scanner-id" in run_call
    assert "AUTH_TOKEN=rest-token" in run_call


def test_ensure_dsxa_container_requires_image() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        _ensure_dsxa_container("dsxa", image="", host_port=15000, container_port=5000, env_values={})

    assert "dsxa_image_required" in str(excinfo.value)


def test_ensure_dsxa_container_requires_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "missing"

    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_run", lambda args: Result())

    with pytest.raises(RuntimeError) as excinfo:
        _ensure_dsxa_container("dsxa", image="repo/dsxa:test", host_port=15000, container_port=5000, env_values={})

    assert "dsxa_env_required" in str(excinfo.value)
    assert "APPLIANCE_URL,TOKEN,SCANNER_ID" in str(excinfo.value)


def test_ensure_dsxa_container_reports_exited_container_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = "exited"
        stderr = ""

    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_run", lambda args: Result())
    monkeypatch.setattr("dsx_connect_ng.local.dsx_connect_ng_local._docker_logs", lambda container_name, tail=100: "bad config")

    with pytest.raises(RuntimeError) as excinfo:
        _ensure_dsxa_container(
            "dsxa",
            image="repo/dsxa:test",
            host_port=15000,
            container_port=5000,
            env_values={"APPLIANCE_URL": "tenant", "TOKEN": "token", "SCANNER_ID": "scanner"},
        )

    assert "dsxa_container_exited" in str(excinfo.value)
    assert "bad config" in str(excinfo.value)


def test_wait_for_rabbitmq_ready_reports_container_state_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    class ExecResult:
        returncode = 1
        stdout = ""
        stderr = "Error response from daemon: No such container: dsx-ng-rabbit"

    monkeypatch.setattr(
        "dsx_connect_ng.local.dsx_connect_ng_local._docker_exec",
        lambda container_name, args: ExecResult(),
    )
    monkeypatch.setattr(
        "dsx_connect_ng.local.dsx_connect_ng_local._rabbitmq_container_state",
        lambda container_name: None,
    )
    monkeypatch.setattr(
        "dsx_connect_ng.local.dsx_connect_ng_local._docker_logs",
        lambda container_name, tail=100: "no logs available",
    )

    with pytest.raises(RuntimeError) as excinfo:
        _wait_for_rabbitmq_ready("dsx-ng-rabbit", timeout_seconds=0.5)

    assert "state=missing" in str(excinfo.value)
    assert "logs=no logs available" in str(excinfo.value)
