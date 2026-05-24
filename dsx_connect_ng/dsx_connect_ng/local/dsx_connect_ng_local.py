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
DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT=1
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
        ServiceSpec(
            name="scan-worker",
            command=[
                python,
                "-m",
                "dsx_connect_ng.workers.scan_worker",
                "--prefetch-count",
                str(base_child_env.get("DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT", "1")),
            ],
            logfile=paths["logs"] / "scan-worker.log",
            cwd=repo / "dsx_connect_ng",
            env=worker_env,
        ),
        ServiceSpec(
            name="policy-worker",
            command=[python, "-m", "dsx_connect_ng.workers.policy_worker"],
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
            command=[python, "-m", "dsx_connect_ng.workers.result_sink_worker"],
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
    return [spec for spec in specs if spec.name in normalized]


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
            "--rm",
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
            "--rm",
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
    overrides["DSX_CONNECT_NG_LOCAL__SCAN_PREFETCH_COUNT"] = str(ctx.obj.get("scan_worker_prefetch_count", 1))
    return overrides


def _prepare_runtime(
    ctx: typer.Context,
    *,
    require_env: bool = True,
) -> tuple[dict[str, Path], list[ServiceSpec], bool, bool, str, str]:
    state_dir = _ctx_state_dir(ctx)
    paths = _ensure_dirs(state_dir)
    if require_env and not paths["env"].exists():
        raise typer.BadParameter(f"env file not found: {paths['env']} (run `init` first)")
    specs = _service_specs(state_dir, extra_env=_runtime_env_overrides(ctx))
    rabbit_container_name = str(ctx.obj["rabbit_container_name"])
    postgres_container_name = str(ctx.obj["postgres_container_name"])
    rabbit_started_by_launcher = False
    postgres_started_by_launcher = False
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
    return (
        paths,
        specs,
        rabbit_started_by_launcher,
        postgres_started_by_launcher,
        rabbit_container_name,
        postgres_container_name,
    )


def _run_services(
    specs: list[ServiceSpec],
    *,
    rabbit_started_by_launcher: bool,
    postgres_started_by_launcher: bool,
    rabbit_container_name: str,
    postgres_container_name: str,
    fail_fast: bool,
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
                thread = threading.Thread(target=_tee_stream, args=(child.stdout, [sys.stdout, logf]), daemon=True)
                thread.start()
                tee_threads.append(thread)
            if child.stderr is not None:
                thread = threading.Thread(target=_tee_stream, args=(child.stderr, [sys.stderr, logf]), daemon=True)
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
    return exit_code


@app.callback()
def main(
    ctx: typer.Context,
    state_dir: str = typer.Option(str(DEFAULT_STATE_DIR), "--state-dir", help="runtime state dir"),
    with_rabbit_docker: bool = typer.Option(False, "--with-rabbit-docker", help="start local RabbitMQ in Docker if needed"),
    rabbit_container_name: str = typer.Option("dsx-ng-rabbit", "--rabbit-container-name", help="RabbitMQ Docker container name"),
    with_postgres_docker: bool = typer.Option(False, "--with-postgres-docker", help="start local Postgres in Docker if needed"),
    postgres_container_name: str = typer.Option("dsx-ng-postgres", "--postgres-container-name", help="Postgres Docker container name"),
    scan_worker_prefetch_count: int = typer.Option(1, "--scan-worker-prefetch-count", min=1, help="number of in-flight scan messages the local scan worker may process concurrently"),
) -> None:
    ctx.obj = {
        "state_dir": state_dir,
        "with_rabbit_docker": with_rabbit_docker,
        "rabbit_container_name": rabbit_container_name,
        "with_postgres_docker": with_postgres_docker,
        "postgres_container_name": postgres_container_name,
        "scan_worker_prefetch_count": scan_worker_prefetch_count,
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
    if overrides:
        print(f"runtime env overrides: {overrides}")
    for spec in _service_specs(state_dir, extra_env=overrides):
        print(f"{spec.name}: log={spec.logfile}")


@app.command("foreground")
def cmd_foreground(ctx: typer.Context) -> None:
    _paths, specs, rabbit_started_by_launcher, postgres_started_by_launcher, rabbit_container_name, postgres_container_name = _prepare_runtime(ctx)
    exit_code = _run_services(
        specs,
        rabbit_started_by_launcher=rabbit_started_by_launcher,
        postgres_started_by_launcher=postgres_started_by_launcher,
        rabbit_container_name=rabbit_container_name,
        postgres_container_name=postgres_container_name,
        fail_fast=True,
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
    _paths, specs, rabbit_started_by_launcher, postgres_started_by_launcher, rabbit_container_name, postgres_container_name = _prepare_runtime(ctx)
    selected = _select_service_specs(specs, service)
    exit_code = _run_services(
        selected,
        rabbit_started_by_launcher=rabbit_started_by_launcher,
        postgres_started_by_launcher=postgres_started_by_launcher,
        rabbit_container_name=rabbit_container_name,
        postgres_container_name=postgres_container_name,
        fail_fast=False,
    )
    if exit_code:
        raise typer.Exit(code=exit_code)


def run() -> None:
    app()
