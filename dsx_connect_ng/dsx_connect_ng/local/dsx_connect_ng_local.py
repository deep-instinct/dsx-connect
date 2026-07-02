#!/usr/bin/env python3
"""Run DSX-Connect NG services locally without containers."""

from __future__ import annotations

import os
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import typer


DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local" / "dsx-connect-ng"
LOCAL_POSTGRES_RELAY_POLL_INTERVAL_SECONDS = 0.25
DSXA_REQUIRED_ENV_KEYS = ("APPLIANCE_URL", "TOKEN", "SCANNER_ID")

app = typer.Typer(help="DSX-Connect NG local runtime manager")
SERVICE_NAMES = {
    "api",
    "relay",
    "scan-worker",
    "policy-worker",
    "remediation-worker",
    "result-sink-worker",
    "dianna-worker",
}
SERVICE_NAME_ALIASES = {
    "delivery-worker": "result-sink-worker",
}


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    cwd: Path
    env: Dict[str, str]
    role: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _runtime_python(repo: Path) -> str:
    candidates = [
        repo / ".venv" / "bin" / "python",
        repo / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return sys.executable


def _state_paths(state_dir: Path) -> dict[str, Path]:
    return {
        "root": state_dir,
        "logs": state_dir / "logs",
        "env": state_dir / ".env.local",
    }


def _ensure_dirs(state_dir: Path) -> dict[str, Path]:
    paths = _state_paths(state_dir)
    for key in ("root", "logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _default_env_template() -> str:
    return """# DSX-Connect NG local runtime env (generated)
DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=postgres
DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq
DSX_CONNECT_NG_RABBITMQ__URL=amqp://dsx:dsx@127.0.0.1:5672/%2F
DSX_CONNECT_NG_POSTGRES__URL=postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_ng
DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA=true
DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT=1000
DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT=1
DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_BATCH_SIZE=1
DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_FLUSH_INTERVAL_SECONDS=1.0
DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES=false
DSX_CONNECT_NG_LOCAL__SCANNER_CLIENT_SCOPE=shared
# Optional when using --with-dsxa-docker.
# DSX_CONNECT_NG_LOCAL__DSXA_IMAGE=dsxconnect/dpa-rocky9:4.2.0.2176
# DSX_CONNECT_NG_LOCAL__DSXA_AUTH_TOKEN=
# DSXA Docker defaults to http://127.0.0.1:15000.
# APPLIANCE_URL=<your-appliance.deepinstinctweb.com>
# TOKEN=<scanner-registration-token>
# SCANNER_ID=<scanner-id>
# FLAVOR=rest,config
# NO_SSL=true
DSX_CONNECT_NG_LOCAL__SCAN_WORKER_SERVICE_IO_THREADED=false
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE=100
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS=0.5
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY=6
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE=scanned
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS=true
DSX_CONNECT_NG_LOCAL__POLICY_PREFETCH_COUNT=1
DSX_CONNECT_NG_LOCAL__RESULT_SINK_PREFETCH_COUNT=1
DSX_CONNECT_NG_RESULT_SINK__BACKEND=stdout
# DSX_CONNECT_NG_RESULT_SINK__BACKEND=json_lines
# DSX_CONNECT_NG_RESULT_SINK__PATH=/tmp/dsx-connect-ng-results.jsonl
DSX_CONNECT_NG__API_PREFIX=/api/v1
"""


def _read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, val = raw.split("=", 1)
        env[key.strip()] = val.strip()
    return env


def _env_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _child_env(env_file: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_read_env_file(env_file))
    repo = _repo_root()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo) if not existing else f"{repo}:{existing}"
    if extra:
        env.update(extra)
    return env


def _service_specs(state_dir: Path, *, extra_env: dict[str, str] | None = None) -> list[ServiceSpec]:
    paths = _state_paths(state_dir)
    repo = _repo_root()
    python = _runtime_python(repo)
    base_child_env = _child_env(paths["env"], extra=extra_env)
    api_env = dict(base_child_env)
    worker_env = dict(base_child_env)
    if "DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA" in worker_env:
        worker_env["DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA"] = "false"
    scan_worker_count = max(1, int(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT", "1")))
    scan_worker_specs = []
    for index in range(scan_worker_count):
        scan_worker_name = "scan-worker" if scan_worker_count == 1 else f"scan-worker-{index + 1}"
        scan_worker_specs.append(
            ServiceSpec(
                name=scan_worker_name,
                role="scan-worker",
                command=[
                    python,
                    "-m",
                    "dsx_connect_ng.workers.scan_worker",
                    "--prefetch-count",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT", "1000")),
                    "--scan-only-completion-batch-size",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_BATCH_SIZE", "1")),
                    "--scan-only-completion-flush-interval-seconds",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_FLUSH_INTERVAL_SECONDS", "1.0")),
                    (
                        "--scan-only-runtime-leases"
                        if _env_bool(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES"), default=False)
                        else "--no-scan-only-runtime-leases"
                    ),
                    "--scanner-client-scope",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCANNER_CLIENT_SCOPE", "shared")),
                    (
                        "--service-io-threaded"
                        if _env_bool(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_WORKER_SERVICE_IO_THREADED"), default=False)
                        else "--no-service-io-threaded"
                    ),
                    "--scan-batch-window-size",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE", "100")),
                    "--scan-batch-window-wait-seconds",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS", "0.5")),
                    "--scan-batch-concurrency",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY", "6")),
                    "--scan-batch-ack-mode",
                    str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE", "scanned")),
                    (
                        "--scan-batch-trust-items"
                        if _env_bool(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS"), default=True)
                        else "--no-scan-batch-trust-items"
                    ),
                ],
                logfile=paths["logs"] / f"{scan_worker_name}.log",
                cwd=repo / "dsx_connect_ng",
                env=worker_env,
            )
        )
    return [
        ServiceSpec(
            name="api",
            command=[python, "-m", "uvicorn", "dsx_connect_ng.app:app", "--host", "127.0.0.1", "--port", "8091"],
            logfile=paths["logs"] / "api.log",
            cwd=repo / "dsx_connect_ng",
            env=api_env,
        ),
        ServiceSpec(
            name="relay",
            command=[python, "-m", "dsx_connect_ng.workers.relay_worker"],
            logfile=paths["logs"] / "relay.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
        *scan_worker_specs,
        ServiceSpec(
            name="policy-worker",
            command=[
                python,
                "-m",
                "dsx_connect_ng.workers.policy_worker",
                "--prefetch-count",
                str(base_child_env.get("DSX_CONNECT_NG_LOCAL__POLICY_PREFETCH_COUNT", "1")),
            ],
            logfile=paths["logs"] / "policy-worker.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
        ServiceSpec(
            name="remediation-worker",
            command=[python, "-m", "dsx_connect_ng.workers.remediation_worker"],
            logfile=paths["logs"] / "remediation-worker.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
        ServiceSpec(
            name="result-sink-worker",
            command=[
                python,
                "-m",
                "dsx_connect_ng.workers.result_sink_worker",
                "--prefetch-count",
                str(base_child_env.get("DSX_CONNECT_NG_LOCAL__RESULT_SINK_PREFETCH_COUNT", "1")),
            ],
            logfile=paths["logs"] / "result-sink-worker.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
        ServiceSpec(
            name="dianna-worker",
            command=[python, "-m", "dsx_connect_ng.workers.dianna_worker"],
            logfile=paths["logs"] / "dianna-worker.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
    ]


def _select_service_specs(specs: list[ServiceSpec], selected_names: list[str] | None = None) -> list[ServiceSpec]:
    if not selected_names:
        return specs
    normalized = {SERVICE_NAME_ALIASES.get(name, name) for name in selected_names}
    unknown = sorted(normalized - SERVICE_NAMES)
    if unknown:
        raise typer.BadParameter(f"unknown service name(s): {', '.join(unknown)}")
    return [spec for spec in specs if spec.name in normalized or spec.role in normalized]


def _docker_binary() -> str:
    found = shutil.which("docker")
    if found:
        return found
    raise RuntimeError("docker_not_found")


def _docker_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    docker = _docker_binary()
    return subprocess.run(
        [docker, *args],
        check=False,
        text=True,
        capture_output=True,
    )


def _rabbitmq_container_state(container_name: str) -> str | None:
    result = _docker_run(["inspect", "-f", "{{.State.Status}}", container_name])
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _docker_exec(container_name: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _docker_run(["exec", container_name, *args])


def _docker_logs(container_name: str, *, tail: int = 100) -> str:
    result = _docker_run(["logs", "--tail", str(tail), container_name])
    if result.returncode != 0:
        return result.stderr.strip() or result.stdout.strip()
    return result.stdout.strip()


def _ensure_rabbitmq_container(container_name: str) -> tuple[bool, str]:
    state = _rabbitmq_container_state(container_name)
    if state == "running":
        return False, f"rabbitmq container already running: {container_name}"
    if state in {"created", "exited"}:
        result = _docker_run(["start", container_name])
        if result.returncode != 0:
            raise RuntimeError(f"docker_start_failed:{result.stderr.strip() or result.stdout.strip()}")
        return True, f"rabbitmq container started: {container_name}"
    result = _docker_run(
        [
            "run",
            "--name",
            container_name,
            "-e",
            "RABBITMQ_DEFAULT_USER=dsx",
            "-e",
            "RABBITMQ_DEFAULT_PASS=dsx",
            "-p",
            "5672:5672",
            "-p",
            "15672:15672",
            "-d",
            "rabbitmq:3-management",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker_run_failed:{result.stderr.strip() or result.stdout.strip()}")
    return True, f"rabbitmq container created: {container_name}"


def _stop_rabbitmq_container(container_name: str) -> None:
    _docker_run(["stop", container_name])


def _ensure_postgres_container(container_name: str) -> tuple[bool, str]:
    state = _rabbitmq_container_state(container_name)
    if state == "running":
        return False, f"postgres container already running: {container_name}"
    if state in {"created", "exited"}:
        result = _docker_run(["start", container_name])
        if result.returncode != 0:
            raise RuntimeError(f"docker_start_failed:{result.stderr.strip() or result.stdout.strip()}")
        return True, f"postgres container started: {container_name}"
    result = _docker_run(
        [
            "run",
            "--name",
            container_name,
            "-e",
            "POSTGRES_USER=dsx",
            "-e",
            "POSTGRES_PASSWORD=dsx",
            "-e",
            "POSTGRES_DB=dsx_connect_ng",
            "-p",
            "5432:5432",
            "-d",
            "postgres:16",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker_run_failed:{result.stderr.strip() or result.stdout.strip()}")
    return True, f"postgres container created: {container_name}"


def _stop_postgres_container(container_name: str) -> None:
    _docker_run(["stop", container_name])


def _ensure_dsxa_container(
    container_name: str,
    *,
    image: str,
    host_port: int,
    container_port: int,
    env_values: dict[str, str],
) -> tuple[bool, str]:
    image = image.strip()
    if not image:
        raise RuntimeError("dsxa_image_required:set --dsxa-image or DSX_CONNECT_NG_LOCAL__DSXA_IMAGE")
    state = _rabbitmq_container_state(container_name)
    if state == "running":
        return False, f"dsxa container already running: {container_name}"
    recreate_reason = state if state in {"created", "exited"} else None
    if recreate_reason:
        result = _docker_run(["rm", container_name])
        if result.returncode != 0:
            raise RuntimeError(f"docker_rm_failed:{result.stderr.strip() or result.stdout.strip()}")
    missing = [key for key in DSXA_REQUIRED_ENV_KEYS if not str(env_values.get(key) or "").strip()]
    if missing:
        raise RuntimeError(
            "dsxa_env_required:"
            f"missing={','.join(missing)}:"
            "set them in --dsxa-env-file or the local .env before using --with-dsxa-docker"
        )
    args = [
        "run",
        "--name",
        container_name,
        "-p",
        f"{host_port}:{container_port}",
    ]
    for key in ("APPLIANCE_URL", "TOKEN", "SCANNER_ID", "FLAVOR", "NO_SSL", "AUTH_TOKEN"):
        value = env_values.get(key)
        if value:
            args.extend(["-e", f"{key}={value}"])
    args.extend(["-d", image])
    result = _docker_run(args)
    if result.returncode != 0:
        raise RuntimeError(f"docker_run_failed:{result.stderr.strip() or result.stdout.strip()}")
    if recreate_reason:
        return True, f"dsxa container recreated from {recreate_reason}: {container_name}"
    return True, f"dsxa container created: {container_name}"


def _stop_dsxa_container(container_name: str) -> None:
    _docker_run(["stop", container_name])


def _wait_for_dsxa_ready(container_name: str, host: str, port: int, *, timeout_seconds: float = 45.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        state = _rabbitmq_container_state(container_name)
        if state is None or state == "exited":
            logs = _docker_logs(container_name, tail=120)
            raise RuntimeError(f"dsxa_not_ready:{container_name}:state={state or 'missing'}:{last_error}:logs={logs}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            sock.close()
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
        finally:
            try:
                sock.close()
            except Exception:
                pass
    logs = _docker_logs(container_name, tail=120)
    raise RuntimeError(f"dsxa_not_ready:{container_name}:state={_rabbitmq_container_state(container_name) or 'missing'}:{last_error}:logs={logs}")


def _wait_for_tcp(host: str, port: int, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            sock.close()
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
        finally:
            try:
                sock.close()
            except Exception:
                pass
    raise RuntimeError(f"service_not_ready:{host}:{port}:{last_error}")


def _wait_for_postgres_ready(container_name: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_output = ""
    while time.time() < deadline:
        result = _docker_exec(container_name, ["pg_isready", "-U", "dsx", "-d", "dsx_connect_ng"])
        if result.returncode == 0:
            return
        last_output = (result.stderr or result.stdout).strip()
        state = _rabbitmq_container_state(container_name)
        if state is None or state == "exited":
            logs = _docker_logs(container_name)
            raise RuntimeError(f"postgres_not_ready:{container_name}:state={state or 'missing'}:{last_output}:logs={logs}")
        time.sleep(0.5)
    raise RuntimeError(f"postgres_not_ready:{container_name}:{last_output}")


def _wait_for_rabbitmq_ready(container_name: str, *, timeout_seconds: float = 45.0) -> None:
    deadline = time.time() + timeout_seconds
    last_output = ""
    while time.time() < deadline:
        result = _docker_exec(container_name, ["rabbitmq-diagnostics", "-q", "ping"])
        if result.returncode == 0:
            return
        last_output = (result.stderr or result.stdout).strip()
        state = _rabbitmq_container_state(container_name)
        if state is None or state == "exited":
            logs = _docker_logs(container_name)
            raise RuntimeError(f"rabbitmq_not_ready:{container_name}:state={state or 'missing'}:{last_output}:logs={logs}")
        time.sleep(0.5)
    raise RuntimeError(f"rabbitmq_not_ready:{container_name}:{last_output}")


def _wait_for_rabbitmq_auth(
    container_name: str,
    *,
    username: str = "dsx",
    password: str = "dsx",
    timeout_seconds: float = 30.0,
) -> None:
    deadline = time.time() + timeout_seconds
    last_output = ""
    while time.time() < deadline:
        result = _docker_exec(container_name, ["rabbitmqctl", "authenticate_user", username, password])
        if result.returncode == 0:
            return
        last_output = (result.stderr or result.stdout).strip()
        time.sleep(0.5)
    raise RuntimeError(f"rabbitmq_auth_not_ready:{container_name}:{last_output}")


async def _probe_rabbitmq_amqp(url: str) -> None:
    import aio_pika

    connection = await aio_pika.connect_robust(url, timeout=5.0)
    try:
        channel = await connection.channel()
        await channel.close()
    finally:
        await connection.close()


def _wait_for_rabbitmq_amqp(url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            asyncio.run(_probe_rabbitmq_amqp(url))
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"rabbitmq_amqp_not_ready:{url}:{last_error}")


def _wait_for_http(url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if 200 <= response.status < 300:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"http_not_ready:{url}:{last_error}")


def _tee_stream(src, outputs: list[object]) -> None:
    try:
        while True:
            chunk = src.readline()
            if not chunk:
                break
            for out in outputs:
                try:
                    out.buffer.write(chunk)
                    out.flush()
                except Exception:
                    try:
                        out.write(chunk)
                        out.flush()
                    except Exception:
                        pass
    finally:
        try:
            src.close()
        except Exception:
            pass


def _ctx_state_dir(ctx: typer.Context) -> Path:
    return Path(ctx.obj["state_dir"]).expanduser()


def _runtime_env_overrides(ctx: typer.Context) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if ctx.obj.get("with_postgres_docker"):
        overrides["DSX_CONNECT_NG__CONTROL_PLANE_BACKEND"] = "postgres"
        overrides["DSX_CONNECT_NG_POSTGRES__URL"] = "postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_ng"
        overrides["DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA"] = "true"
    if ctx.obj.get("with_rabbit_docker"):
        overrides["DSX_CONNECT_NG__JOB_BUS_BACKEND"] = "rabbitmq"
        overrides["DSX_CONNECT_NG_RABBITMQ__URL"] = "amqp://dsx:dsx@127.0.0.1:5672/%2F"
        overrides["DSX_CONNECT_NG_RABBITMQ__PUBLISHER_CONFIRMS"] = "false"
    if ctx.obj.get("with_dsxa_docker"):
        dsxa_scheme = str(ctx.obj.get("dsxa_scheme", "http"))
        overrides["DSX_CONNECT_NG_SCANNER__MODE"] = "dsxa"
        overrides["DSX_CONNECT_NG_SCANNER__BASE_URL"] = f"{dsxa_scheme}://127.0.0.1:{ctx.obj.get('dsxa_host_port', 15000)}"
        overrides["DSX_CONNECT_NG_SCANNER__VERIFY_TLS"] = str(ctx.obj.get("dsxa_verify_tls", False)).lower()
        auth_token = ctx.obj.get("dsxa_auth_token")
        if auth_token:
            overrides["DSX_CONNECT_NG_SCANNER__AUTH_TOKEN"] = str(auth_token)
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT"] = str(ctx.obj.get("scan_worker_prefetch_count", 1000))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_WORKER_COUNT"] = str(ctx.obj.get("scan_worker_count", 1))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_BATCH_SIZE"] = str(ctx.obj.get("scan_only_completion_batch_size", 1))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_ONLY_COMPLETION_FLUSH_INTERVAL_SECONDS"] = str(ctx.obj.get("scan_only_completion_flush_interval_seconds", 1.0))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_ONLY_RUNTIME_LEASES"] = str(ctx.obj.get("scan_only_runtime_leases", False)).lower()
    overrides["DSX_CONNECT_NG_LOCAL__SCANNER_CLIENT_SCOPE"] = str(ctx.obj.get("scanner_client_scope", "shared"))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_WORKER_SERVICE_IO_THREADED"] = str(ctx.obj.get("scan_worker_service_io_threaded", False)).lower()
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_SIZE"] = str(ctx.obj.get("scan_batch_window_size", 100))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_BATCH_WINDOW_WAIT_SECONDS"] = str(ctx.obj.get("scan_batch_window_wait_seconds", 0.5))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_BATCH_CONCURRENCY"] = str(ctx.obj.get("scan_batch_concurrency", 6))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ACK_MODE"] = str(ctx.obj.get("scan_batch_ack_mode", "scanned"))
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_BATCH_TRUST_ITEMS"] = str(ctx.obj.get("scan_batch_trust_items", True)).lower()
    overrides["DSX_CONNECT_NG_LOCAL__POLICY_PREFETCH_COUNT"] = str(ctx.obj.get("policy_worker_prefetch_count", 1))
    overrides["DSX_CONNECT_NG_LOCAL__RESULT_SINK_PREFETCH_COUNT"] = str(ctx.obj.get("result_sink_worker_prefetch_count", 1))
    relay_max_active_scan_items = ctx.obj.get("relay_max_active_scan_items")
    if relay_max_active_scan_items is not None:
        overrides["DSX_CONNECT_NG_RELAY__MAX_ACTIVE_SCAN_ITEMS"] = str(relay_max_active_scan_items)
    relay_batch_size = ctx.obj.get("relay_batch_size")
    if relay_batch_size is not None:
        overrides["DSX_CONNECT_NG_RELAY__BATCH_SIZE"] = str(relay_batch_size)
    relay_poll_interval_seconds = ctx.obj.get("relay_poll_interval_seconds")
    if relay_poll_interval_seconds is not None:
        overrides["DSX_CONNECT_NG_RELAY__POLL_INTERVAL_SECONDS"] = str(relay_poll_interval_seconds)
    elif ctx.obj.get("with_postgres_docker"):
        overrides["DSX_CONNECT_NG_RELAY__POLL_INTERVAL_SECONDS"] = str(LOCAL_POSTGRES_RELAY_POLL_INTERVAL_SECONDS)
    return overrides


def _dsxa_docker_env(ctx: typer.Context, env_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_read_env_file(env_path))
    dsxa_env_file = str(ctx.obj.get("dsxa_env_file") or "").strip()
    if dsxa_env_file:
        env.update(_read_env_file(Path(dsxa_env_file).expanduser()))
    if ctx.obj.get("dsxa_auth_token"):
        env["AUTH_TOKEN"] = str(ctx.obj["dsxa_auth_token"])
    return env


def _prepare_runtime(
    ctx: typer.Context,
    *,
    require_env: bool = True,
) -> tuple[dict[str, Path], list[ServiceSpec], bool, bool, bool, str, str, str]:
    state_dir = _ctx_state_dir(ctx)
    paths = _ensure_dirs(state_dir)
    if require_env and not paths["env"].exists():
        raise typer.BadParameter(f"env file not found: {paths['env']} (run `init` first)")
    specs = _service_specs(state_dir, extra_env=_runtime_env_overrides(ctx))
    rabbit_container_name = str(ctx.obj["rabbit_container_name"])
    postgres_container_name = str(ctx.obj["postgres_container_name"])
    dsxa_container_name = str(ctx.obj["dsxa_container_name"])
    rabbit_started_by_launcher = False
    postgres_started_by_launcher = False
    dsxa_started_by_launcher = False
    try:
        if ctx.obj.get("with_postgres_docker"):
            postgres_started_by_launcher, message = _ensure_postgres_container(postgres_container_name)
            print(message)
            _wait_for_tcp("127.0.0.1", 5432)
            _wait_for_postgres_ready(postgres_container_name)
            print("postgres ready on 127.0.0.1:5432")
        if ctx.obj.get("with_rabbit_docker"):
            rabbit_started_by_launcher, message = _ensure_rabbitmq_container(rabbit_container_name)
            print(message)
            _wait_for_tcp("127.0.0.1", 5672)
            _wait_for_rabbitmq_ready(rabbit_container_name)
            _wait_for_rabbitmq_auth(rabbit_container_name)
            _wait_for_rabbitmq_amqp("amqp://dsx:dsx@127.0.0.1:5672/%2F")
            print("rabbitmq ready on 127.0.0.1:5672")
        if ctx.obj.get("with_dsxa_docker"):
            dsxa_started_by_launcher, message = _ensure_dsxa_container(
                dsxa_container_name,
                image=str(ctx.obj.get("dsxa_image") or ""),
                host_port=int(ctx.obj.get("dsxa_host_port", 15000)),
                container_port=int(ctx.obj.get("dsxa_container_port", 5000)),
                env_values=_dsxa_docker_env(ctx, paths["env"]),
            )
            print(message)
            _wait_for_dsxa_ready(dsxa_container_name, "127.0.0.1", int(ctx.obj.get("dsxa_host_port", 15000)))
            print(
                f"dsxa ready on {ctx.obj.get('dsxa_scheme', 'http')}://"
                f"127.0.0.1:{ctx.obj.get('dsxa_host_port', 15000)}"
            )
    except Exception:
        if dsxa_started_by_launcher:
            _stop_dsxa_container(dsxa_container_name)
        if rabbit_started_by_launcher:
            _stop_rabbitmq_container(rabbit_container_name)
        if postgres_started_by_launcher:
            _stop_postgres_container(postgres_container_name)
        raise
    return (
        paths,
        specs,
        rabbit_started_by_launcher,
        postgres_started_by_launcher,
        dsxa_started_by_launcher,
        rabbit_container_name,
        postgres_container_name,
        dsxa_container_name,
    )


def _run_services(
    specs: list[ServiceSpec],
    *,
    rabbit_started_by_launcher: bool,
    postgres_started_by_launcher: bool,
    dsxa_started_by_launcher: bool,
    rabbit_container_name: str,
    postgres_container_name: str,
    dsxa_container_name: str,
    fail_fast: bool,
    stream_logs: bool,
) -> int:
    children: list[tuple[ServiceSpec, subprocess.Popen]] = []
    tee_threads: list[threading.Thread] = []
    log_handles = []
    stop_requested = False
    exit_code = 0

    def _on_signal(signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        print(f"received signal {signum}; shutting down...")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        selected_names = {spec.name for spec in specs}
        ordered_specs = []
        api_spec = next((spec for spec in specs if spec.name == "api"), None)
        if api_spec is not None:
            ordered_specs.append(api_spec)
        ordered_specs.extend(spec for spec in specs if spec.name != "api")

        for spec in ordered_specs:
            print(f"starting {spec.name} (foreground)")
            spec.logfile.parent.mkdir(parents=True, exist_ok=True)
            logf = spec.logfile.open("ab")
            log_handles.append(logf)
            child = subprocess.Popen(
                spec.command,
                cwd=str(spec.cwd),
                env=spec.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            children.append((spec, child))
            if child.stdout is not None:
                outputs = [sys.stdout, logf] if stream_logs else [logf]
                thread = threading.Thread(target=_tee_stream, args=(child.stdout, outputs), daemon=True)
                thread.start()
                tee_threads.append(thread)
            if child.stderr is not None:
                outputs = [sys.stderr, logf] if stream_logs else [logf]
                thread = threading.Thread(target=_tee_stream, args=(child.stderr, outputs), daemon=True)
                thread.start()
                tee_threads.append(thread)
            if spec.name == "api":
                _wait_for_http("http://127.0.0.1:8091/api/v1/health")
                print("api ready on http://127.0.0.1:8091/api/v1/health")

        live_children = {child.pid for _spec, child in children}
        while not stop_requested and live_children:
            for spec, child in children:
                if child.pid not in live_children:
                    continue
                rc = child.poll()
                if rc is None:
                    continue
                live_children.remove(child.pid)
                exit_code = rc if rc else exit_code
                if fail_fast:
                    stop_requested = True
                    break
                print(f"{spec.name} exited with code {rc}")
            time.sleep(0.2)
    finally:
        for _spec, child in reversed(children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except Exception:
                    child.terminate()
        deadline = time.time() + 8.0
        for _spec, child in reversed(children):
            while child.poll() is None and time.time() < deadline:
                time.sleep(0.1)
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except Exception:
                    child.kill()
        for _spec, child in children:
            try:
                child.wait(timeout=1)
            except Exception:
                pass
        for thread in tee_threads:
            thread.join(timeout=1)
        for logf in log_handles:
            try:
                logf.close()
            except Exception:
                pass
        if rabbit_started_by_launcher:
            _stop_rabbitmq_container(rabbit_container_name)
        if postgres_started_by_launcher:
            _stop_postgres_container(postgres_container_name)
        if dsxa_started_by_launcher:
            _stop_dsxa_container(dsxa_container_name)
    return exit_code


@app.callback()
def main(
    ctx: typer.Context,
    state_dir: str = typer.Option(str(DEFAULT_STATE_DIR), "--state-dir", help="runtime state dir"),
    with_rabbit_docker: bool = typer.Option(False, "--with-rabbit-docker", help="start local RabbitMQ in Docker if needed"),
    rabbit_container_name: str = typer.Option("dsx-ng-rabbit", "--rabbit-container-name", help="RabbitMQ Docker container name"),
    with_postgres_docker: bool = typer.Option(False, "--with-postgres-docker", help="start local Postgres in Docker if needed"),
    postgres_container_name: str = typer.Option("dsx-ng-postgres", "--postgres-container-name", help="Postgres Docker container name"),
    with_dsxa_docker: bool = typer.Option(False, "--with-dsxa-docker", help="start local DSXA scanner in Docker if needed and configure NG scanner mode"),
    dsxa_container_name: str = typer.Option("dsx-ng-dsxa", "--dsxa-container-name", help="DSXA Docker container name"),
    dsxa_image: str = typer.Option("", "--dsxa-image", envvar="DSX_CONNECT_NG_LOCAL__DSXA_IMAGE", help="DSXA Docker image to run"),
    dsxa_host_port: int = typer.Option(15000, "--dsxa-host-port", min=1, help="host port for DSXA scanner"),
    dsxa_container_port: int = typer.Option(5000, "--dsxa-container-port", min=1, help="container port exposed by the DSXA scanner image"),
    dsxa_scheme: str = typer.Option("http", "--dsxa-scheme", help="scheme for the local DSXA scanner URL: http or https"),
    dsxa_verify_tls: bool = typer.Option(False, "--dsxa-verify-tls/--no-dsxa-verify-tls", help="verify TLS certificates when NG connects to local DSXA Docker"),
    dsxa_env_file: str = typer.Option("", "--dsxa-env-file", help="optional env file containing APPLIANCE_URL, TOKEN, SCANNER_ID, FLAVOR, NO_SSL, AUTH_TOKEN"),
    dsxa_auth_token: str = typer.Option("", "--dsxa-auth-token", envvar="DSX_CONNECT_NG_LOCAL__DSXA_AUTH_TOKEN", help="optional DSXA REST auth token; also passed to NG scanner config"),
    scan_worker_prefetch_count: int = typer.Option(1000, "--scan-worker-prefetch-count", min=1, help="number of in-flight scan messages the local scan worker may process concurrently"),
    scan_worker_count: int = typer.Option(1, "--scan-worker-count", min=1, help="number of local scan worker processes to start"),
    scan_only_completion_batch_size: int = typer.Option(1, "--scan-only-completion-batch-size", min=1, help="number of scan-only item completions each worker buffers before bulk persistence"),
    scan_only_completion_flush_interval_seconds: float = typer.Option(1.0, "--scan-only-completion-flush-interval-seconds", min=0.05, help="maximum age for buffered scan-only completions before bulk persistence"),
    scan_only_runtime_leases: bool = typer.Option(False, "--scan-only-runtime-leases/--no-scan-only-runtime-leases", help="record runtime scan leases for coarse scan-only batch work"),
    scanner_client_scope: str = typer.Option("shared", "--scanner-client-scope", help="DSXA client lifetime used by scan workers: shared or per-task"),
    scan_worker_service_io_threaded: bool = typer.Option(False, "--scan-worker-service-io-threaded/--no-scan-worker-service-io-threaded", help="run synchronous scan worker JobService calls in worker threads"),
    scan_batch_window_size: int = typer.Option(100, "--scan-batch-window-size", min=1, help="collect this many coarse scan-only completions before bulk persistence"),
    scan_batch_window_wait_seconds: float = typer.Option(0.5, "--scan-batch-window-wait-seconds", min=0.001, help="maximum wait for partial scan-only completions before bulk persistence"),
    scan_batch_concurrency: int = typer.Option(6, "--scan-batch-concurrency", min=0, help="concurrent read/scan coroutines inside each scan-only batch window; 0 uses scan prefetch"),
    scan_batch_ack_mode: str = typer.Option("scanned", "--scan-batch-ack-mode", help="scan-only batch ack mode: completed, scanned, or accepted"),
    scan_batch_trust_items: bool = typer.Option(True, "--scan-batch-trust-items/--no-scan-batch-trust-items", help="skip per-item DB reads around scan-only pooled scans"),
    policy_worker_prefetch_count: int = typer.Option(1, "--policy-worker-prefetch-count", min=1, help="number of in-flight policy messages the local policy worker may process concurrently"),
    result_sink_worker_prefetch_count: int = typer.Option(1, "--result-sink-worker-prefetch-count", min=1, help="number of in-flight result-sink messages the local result-sink worker may process concurrently"),
    relay_max_active_scan_items: int | None = typer.Option(None, "--relay-max-active-scan-items", min=1, help="maximum queued/scanning/scanned items before the relay pauses publishing"),
    relay_batch_size: int | None = typer.Option(None, "--relay-batch-size", min=1, help="maximum outbox records the local relay publishes per flush"),
    relay_poll_interval_seconds: float | None = typer.Option(None, "--relay-poll-interval-seconds", min=0.05, help="sleep interval between local relay flush cycles"),
    stream_logs: bool = typer.Option(True, "--stream-logs/--no-stream-logs", help="stream child service logs to this terminal in addition to log files"),
) -> None:
    if scanner_client_scope not in {"shared", "per-task"}:
        raise typer.BadParameter("scanner_client_scope must be one of: shared, per-task")
    if scan_batch_ack_mode not in {"completed", "scanned", "accepted"}:
        raise typer.BadParameter("scan_batch_ack_mode must be one of: completed, scanned, accepted")
    if dsxa_scheme not in {"http", "https"}:
        raise typer.BadParameter("dsxa_scheme must be one of: http, https")
    ctx.obj = {
        "state_dir": state_dir,
        "with_rabbit_docker": with_rabbit_docker,
        "rabbit_container_name": rabbit_container_name,
        "with_postgres_docker": with_postgres_docker,
        "postgres_container_name": postgres_container_name,
        "with_dsxa_docker": with_dsxa_docker,
        "dsxa_container_name": dsxa_container_name,
        "dsxa_image": dsxa_image,
        "dsxa_host_port": dsxa_host_port,
        "dsxa_container_port": dsxa_container_port,
        "dsxa_scheme": dsxa_scheme,
        "dsxa_verify_tls": dsxa_verify_tls,
        "dsxa_env_file": dsxa_env_file,
        "dsxa_auth_token": dsxa_auth_token,
        "scan_worker_prefetch_count": scan_worker_prefetch_count,
        "scan_worker_count": scan_worker_count,
        "scan_only_completion_batch_size": scan_only_completion_batch_size,
        "scan_only_completion_flush_interval_seconds": scan_only_completion_flush_interval_seconds,
        "scan_only_runtime_leases": scan_only_runtime_leases,
        "scanner_client_scope": scanner_client_scope,
        "scan_worker_service_io_threaded": scan_worker_service_io_threaded,
        "scan_batch_window_size": scan_batch_window_size,
        "scan_batch_window_wait_seconds": scan_batch_window_wait_seconds,
        "scan_batch_concurrency": scan_batch_concurrency,
        "scan_batch_ack_mode": scan_batch_ack_mode,
        "scan_batch_trust_items": scan_batch_trust_items,
        "policy_worker_prefetch_count": policy_worker_prefetch_count,
        "result_sink_worker_prefetch_count": result_sink_worker_prefetch_count,
        "relay_max_active_scan_items": relay_max_active_scan_items,
        "relay_batch_size": relay_batch_size,
        "relay_poll_interval_seconds": relay_poll_interval_seconds,
        "stream_logs": stream_logs,
    }


@app.command("init")
def cmd_init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="overwrite existing .env.local"),
) -> None:
    state_dir = _ctx_state_dir(ctx)
    paths = _ensure_dirs(state_dir)
    env_file = paths["env"]
    if env_file.exists() and not force:
        print(f"env exists: {env_file}")
    else:
        env_file.write_text(_default_env_template())
        print(f"wrote env template: {env_file}")
    print(f"state dir ready: {state_dir}")


@app.command("status")
def cmd_status(ctx: typer.Context) -> None:
    state_dir = _ctx_state_dir(ctx)
    paths = _ensure_dirs(state_dir)
    overrides = _runtime_env_overrides(ctx)
    print(f"state dir: {state_dir}")
    print(f"env file: {paths['env']}")
    if ctx.obj.get("with_rabbit_docker"):
        name = str(ctx.obj["rabbit_container_name"])
        print(f"rabbit docker: {name} state={_rabbitmq_container_state(name) or 'missing'}")
    if ctx.obj.get("with_postgres_docker"):
        name = str(ctx.obj["postgres_container_name"])
        print(f"postgres docker: {name} state={_rabbitmq_container_state(name) or 'missing'}")
    if ctx.obj.get("with_dsxa_docker"):
        name = str(ctx.obj["dsxa_container_name"])
        print(f"dsxa docker: {name} state={_rabbitmq_container_state(name) or 'missing'}")
    if overrides:
        print(f"runtime env overrides: {overrides}")
    for spec in _service_specs(state_dir, extra_env=overrides):
        print(f"{spec.name}: log={spec.logfile}")


@app.command("foreground")
def cmd_foreground(ctx: typer.Context) -> None:
    (
        _paths,
        specs,
        rabbit_started_by_launcher,
        postgres_started_by_launcher,
        dsxa_started_by_launcher,
        rabbit_container_name,
        postgres_container_name,
        dsxa_container_name,
    ) = _prepare_runtime(ctx)
    exit_code = _run_services(
        specs,
        rabbit_started_by_launcher=rabbit_started_by_launcher,
        postgres_started_by_launcher=postgres_started_by_launcher,
        dsxa_started_by_launcher=dsxa_started_by_launcher,
        rabbit_container_name=rabbit_container_name,
        postgres_container_name=postgres_container_name,
        dsxa_container_name=dsxa_container_name,
        fail_fast=True,
        stream_logs=bool(ctx.obj.get("stream_logs", True)),
    )
    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command("debug")
def cmd_debug(
    ctx: typer.Context,
    service: list[str] = typer.Option(
        [],
        "--service",
        "-s",
        help="service(s) to run: api, relay, scan-worker, policy-worker, remediation-worker, result-sink-worker, dianna-worker (legacy alias: delivery-worker)",
    ),
) -> None:
    (
        _paths,
        specs,
        rabbit_started_by_launcher,
        postgres_started_by_launcher,
        dsxa_started_by_launcher,
        rabbit_container_name,
        postgres_container_name,
        dsxa_container_name,
    ) = _prepare_runtime(ctx)
    selected = _select_service_specs(specs, service)
    exit_code = _run_services(
        selected,
        rabbit_started_by_launcher=rabbit_started_by_launcher,
        postgres_started_by_launcher=postgres_started_by_launcher,
        dsxa_started_by_launcher=dsxa_started_by_launcher,
        rabbit_container_name=rabbit_container_name,
        postgres_container_name=postgres_container_name,
        dsxa_container_name=dsxa_container_name,
        fail_fast=False,
        stream_logs=bool(ctx.obj.get("stream_logs", True)),
    )
    if exit_code:
        raise typer.Exit(code=exit_code)


def run() -> None:
    app()


if __name__ == "__main__":
    run()
