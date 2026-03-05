#!/usr/bin/env python3
"""Run DSX-Connect core + workers + redis locally without Docker/K8s."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import typer


SERVICE_ORDER = ["redis", "api", "workers"]
DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local"
DEFAULT_REDIS_PORT = 6380

app = typer.Typer(help="DSX-Connect local runtime manager (macOS-first MVP)")


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    pidfile: Path
    cwd: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_paths(state_dir: Path) -> Dict[str, Path]:
    return {
        "root": state_dir,
        "logs": state_dir / "logs",
        "pids": state_dir / "run",
        "data": state_dir / "data",
        "redis": state_dir / "data" / "redis",
        "env": state_dir / ".env.local",
        "redis_conf": state_dir / "redis.conf",
    }


def _ensure_dirs(state_dir: Path) -> Dict[str, Path]:
    paths = _state_paths(state_dir)
    for key in ("root", "logs", "pids", "data", "redis"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _default_env_template(redis_port: int) -> str:
    return f"""# DSX-Connect local runtime env (generated)
# Edit scanner URL/token and optional DIANNA settings as needed.

LOG_LEVEL=debug

# DSXA scanner endpoint
DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://127.0.0.1:15000/scan/binary/v2
DSXCONNECT_SCANNER__AUTH_TOKEN=

# Local Redis layout (single redis process, separate DB indexes)
DSXCONNECT_REDIS_URL=redis://127.0.0.1:{redis_port}/3
DSXCONNECT_RESULTS_DB=redis://127.0.0.1:{redis_port}/3
DSXCONNECT_RESULTS_DB__RETAIN=1000
DSXCONNECT_WORKERS__BROKER=redis://127.0.0.1:{redis_port}/5
DSXCONNECT_WORKERS__BACKEND=redis://127.0.0.1:{redis_port}/6

# Local API transport
DSXCONNECT_USE_TLS=false

# Optional auth
DSXCONNECT_AUTH__ENABLED=false
DSXCONNECT_AUTH__ENROLLMENT_TOKEN=abc123

# Optional DIANNA
DSXCONNECT_DIANNA__ENABLED=false
DSXCONNECT_DIANNA__AUTO_ON_MALICIOUS=false

# Persist UI-driven core config edits only for local runtime
DSXCONNECT_CONFIG_PERSIST_LOCAL_ONLY=true
"""


def _pid_from_file(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except Exception:
        return None


def _is_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def _remove_pid(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _wait_for_pid(pid: int, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_pid_alive(pid):
            return True
        time.sleep(0.1)
    return _is_pid_alive(pid)


def _terminate_pid(pid: int, grace_seconds: float = 8.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _service_specs(state_dir: Path, redis_port: int) -> Dict[str, ServiceSpec]:
    paths = _state_paths(state_dir)
    repo = _repo_root()
    python = sys.executable
    redis_pidfile = paths["pids"] / "redis.pid"
    api_pidfile = paths["pids"] / "api.pid"
    workers_pidfile = paths["pids"] / "workers.pid"

    redis_conf = f"""bind 127.0.0.1
port {redis_port}
dir {paths['redis']}
dbfilename dump.rdb
save ""
appendonly no
pidfile {redis_pidfile}
"""
    paths["redis_conf"].write_text(redis_conf)

    redis_cmd = ["redis-server", str(paths["redis_conf"])]
    api_cmd = [python, str(repo / "dsx_connect" / "dsx-connect-api-start.py")]
    workers_cmd = [python, str(repo / "dsx_connect" / "dsx-connect-workers-start.py")]

    return {
        "redis": ServiceSpec(
            name="redis",
            command=redis_cmd,
            logfile=paths["logs"] / "redis.log",
            pidfile=redis_pidfile,
            cwd=repo,
        ),
        "api": ServiceSpec(
            name="api",
            command=api_cmd,
            logfile=paths["logs"] / "api.log",
            pidfile=api_pidfile,
            cwd=repo,
        ),
        "workers": ServiceSpec(
            name="workers",
            command=workers_cmd,
            logfile=paths["logs"] / "workers.log",
            pidfile=workers_pidfile,
            cwd=repo,
        ),
    }


def _spawn(spec: ServiceSpec, child_env: Dict[str, str]) -> int:
    with spec.logfile.open("ab") as log_fp:
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=child_env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def _child_env(env_file: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env["DSXCONNECTOR_ENV_FILE"] = str(env_file)

    repo = str(_repo_root())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo if not existing else f"{repo}:{existing}"
    return env


def _ctx_values(ctx: typer.Context) -> tuple[Path, int]:
    state_dir = Path(ctx.obj["state_dir"]).expanduser()
    redis_port = int(ctx.obj["redis_port"])
    return state_dir, redis_port


@app.callback()
def main(
    ctx: typer.Context,
    state_dir: str = typer.Option(str(DEFAULT_STATE_DIR), "--state-dir", help="runtime state dir"),
    redis_port: int = typer.Option(DEFAULT_REDIS_PORT, "--redis-port", help="local redis port"),
) -> None:
    ctx.obj = {
        "state_dir": state_dir,
        "redis_port": redis_port,
    }


@app.command("init")
def cmd_init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="overwrite existing .env.local"),
) -> None:
    state_dir, redis_port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_file = paths["env"]
    if env_file.exists() and not force:
        print(f"env exists: {env_file}")
    else:
        env_file.write_text(_default_env_template(redis_port))
        print(f"wrote env template: {env_file}")
    print(f"state dir ready: {state_dir}")


@app.command("start")
def cmd_start(
    ctx: typer.Context,
    env_file: str | None = typer.Option(None, "--env-file", help="override env file path"),
) -> None:
    state_dir, redis_port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_path = Path(env_file).expanduser() if env_file else paths["env"]
    if not env_path.exists():
        print(f"missing env file: {env_path}")
        print("run: python dsx_connect/local/dsx_connect_local.py init")
        raise typer.Exit(code=1)

    specs = _service_specs(state_dir, redis_port)
    child_env = _child_env(env_path)

    for svc in SERVICE_ORDER:
        spec = specs[svc]
        pid = _pid_from_file(spec.pidfile)
        if _is_pid_alive(pid):
            print(f"{svc}: already running (pid={pid})")
            continue
        if svc == "redis" and shutil.which("redis-server") is None:
            print("redis-server not found in PATH. Install redis first (e.g., brew install redis).")
            raise typer.Exit(code=1)

        pid = _spawn(spec, child_env)
        if not _wait_for_pid(pid):
            print(f"{svc}: failed to start, check log {spec.logfile}")
            raise typer.Exit(code=1)

        time.sleep(0.7)
        if not _is_pid_alive(pid):
            print(f"{svc}: exited during startup, check log {spec.logfile}")
            raise typer.Exit(code=1)

        _write_pid(spec.pidfile, pid)
        print(f"{svc}: started pid={pid} log={spec.logfile}")


@app.command("stop")
def cmd_stop(
    ctx: typer.Context,
    grace_seconds: float = typer.Option(8.0, "--grace-seconds", help="shutdown grace period"),
) -> None:
    state_dir, redis_port = _ctx_values(ctx)
    specs = _service_specs(state_dir, redis_port)

    for svc in reversed(SERVICE_ORDER):
        spec = specs[svc]
        pid = _pid_from_file(spec.pidfile)
        if not _is_pid_alive(pid):
            _remove_pid(spec.pidfile)
            print(f"{svc}: not running")
            continue
        _terminate_pid(pid, grace_seconds=grace_seconds)
        _remove_pid(spec.pidfile)
        print(f"{svc}: stopped")


@app.command("status")
def cmd_status(ctx: typer.Context) -> None:
    state_dir, redis_port = _ctx_values(ctx)
    specs = _service_specs(state_dir, redis_port)
    exit_code = 0

    for svc in SERVICE_ORDER:
        spec = specs[svc]
        pid = _pid_from_file(spec.pidfile)
        alive = _is_pid_alive(pid)
        state = "running" if alive else "stopped"
        if not alive:
            exit_code = 1
        print(f"{svc:8} {state:8} pid={pid if pid else '-'} log={spec.logfile}")

    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command("logs")
def cmd_logs(
    ctx: typer.Context,
    service: str = typer.Argument(..., help="service name"),
    lines: int = typer.Option(50, "--lines", help="tail lines"),
) -> None:
    state_dir, redis_port = _ctx_values(ctx)
    specs = _service_specs(state_dir, redis_port)
    if service not in specs:
        print(f"unknown service: {service}")
        raise typer.Exit(code=1)

    log_file = specs[service].logfile
    if not log_file.exists():
        print(f"log not found: {log_file}")
        raise typer.Exit(code=1)

    content = log_file.read_text(errors="replace").splitlines()
    for line in content[-lines:]:
        print(line)


if __name__ == "__main__":
    app()
