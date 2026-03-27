#!/usr/bin/env python3
"""Run filesystem connector locally without Docker/K8s."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict

import typer


DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local" / "filesystem-connector"
DEFAULT_PORT = 8620

app = typer.Typer(help="Filesystem connector local runtime manager")


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    pidfile: Path
    cwd: Path


def _is_filesystem_repo_root(path: Path) -> bool:
    return (path / "connectors" / "filesystem" / "start.py").exists()


def _repo_root() -> Path:
    override = os.getenv("DSXCONNECT_LOCAL_REPO_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if _is_filesystem_repo_root(p):
            return p
        raise RuntimeError(
            f"DSXCONNECT_LOCAL_REPO_ROOT is set but invalid: {p}"
        )

    source_guess = Path(__file__).resolve().parents[3]
    if _is_filesystem_repo_root(source_guess):
        return source_guess

    if getattr(sys, "frozen", False):
        exe = Path(sys.argv[0]).resolve()
        if len(exe.parents) >= 6:
            app_guess = exe.parents[5]
            if _is_filesystem_repo_root(app_guess):
                return app_guess

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _is_filesystem_repo_root(candidate):
            return candidate

    raise RuntimeError(
        "Could not locate DSX-Connect repo root. Run from repo root or set "
        "DSXCONNECT_LOCAL_REPO_ROOT=/path/to/dsx-connect"
    )


def _runtime_python(repo: Path) -> str:
    override = os.getenv("DSXCONNECT_LOCAL_PYTHON", "").strip()
    candidates = []
    if override:
        candidates.append(override)
    candidates.append(str(repo / ".venv" / "bin" / "python"))

    py3 = shutil.which("python3")
    if py3:
        candidates.append(py3)

    for candidate in candidates:
        if candidate and Path(candidate).exists() and os.access(candidate, os.X_OK):
            return candidate

    raise RuntimeError(
        "No usable Python interpreter found for launching connector. "
        "Set DSXCONNECT_LOCAL_PYTHON or ensure .venv/bin/python exists."
    )


def _state_paths(state_dir: Path) -> Dict[str, Path]:
    return {
        "root": state_dir,
        "logs": state_dir / "logs",
        "run": state_dir / "run",
        "data": state_dir / "data",
        "scan": state_dir / "data" / "scan",
        "quarantine": state_dir / "data" / "quarantine",
        "env": state_dir / ".env.local",
    }


def _ensure_dirs(state_dir: Path) -> Dict[str, Path]:
    paths = _state_paths(state_dir)
    for key in ("root", "logs", "run", "data", "scan", "quarantine"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _default_env_template(*, state_dir: Path, port: int) -> str:
    paths = _state_paths(state_dir)
    return f"""# Filesystem connector local runtime env (generated)

LOG_LEVEL=debug

# Connector endpoints
DSXCONNECTOR_CONNECTOR_URL=http://127.0.0.1:{port}
DSXCONNECTOR_DSX_CONNECT_URL=http://127.0.0.1:8586

# Filesystem source + quarantine
DSXCONNECTOR_ASSET={paths['scan']}
DSXCONNECTOR_ASSET_DISPLAY_NAME={paths['scan']}
DSXCONNECTOR_ITEM_ACTION=nothing
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO={paths['quarantine']}
# Persist config edits from UI back into this .env.local (local runtime only)
DSXCONNECTOR_CONFIG_PERSIST_LOCAL_ONLY=true

# Optional monitoring
DSXCONNECTOR_MONITOR=true
DSXCONNECTOR_MONITOR_FORCE_POLLING=true
DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS=1000

# Optional auth
DSXCONNECTOR_AUTH__ENABLED=false
#DSXCONNECT_ENROLLMENT_TOKEN=abc123

# Optional TLS
DSXCONNECTOR_USE_TLS=false
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


def _service_spec(state_dir: Path, *, port: int, host: str, workers: int, reload: bool) -> ServiceSpec:
    paths = _state_paths(state_dir)
    repo = _repo_root()
    python = _runtime_python(repo)

    cmd = [
        python,
        str(repo / "connectors" / "filesystem" / "start.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--reload" if reload else "--no-reload",
    ]

    return ServiceSpec(
        name="filesystem-connector",
        command=cmd,
        logfile=paths["logs"] / "filesystem-connector.log",
        pidfile=paths["run"] / "filesystem-connector.pid",
        cwd=repo,
    )


def _child_env(env_file: Path) -> Dict[str, str]:
    env = os.environ.copy()
    env["DSXCONNECTOR_ENV_FILE"] = str(env_file)

    repo = str(_repo_root())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo if not existing else f"{repo}:{existing}"
    return env


def _ctx_values(ctx: typer.Context) -> tuple[Path, int]:
    state_dir = Path(ctx.obj["state_dir"]).expanduser()
    port = int(ctx.obj["port"])
    return state_dir, port


@app.callback()
def main(
    ctx: typer.Context,
    state_dir: str = typer.Option(str(DEFAULT_STATE_DIR), "--state-dir", help="runtime state dir"),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="connector port"),
) -> None:
    ctx.obj = {
        "state_dir": state_dir,
        "port": port,
    }


@app.command("init")
def cmd_init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="overwrite existing .env.local"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_file = paths["env"]
    if env_file.exists() and not force:
        print(f"env exists: {env_file}")
    else:
        env_file.write_text(_default_env_template(state_dir=state_dir, port=port))
        print(f"wrote env template: {env_file}")
    print(f"state dir ready: {state_dir}")


@app.command("start")
def cmd_start(
    ctx: typer.Context,
    env_file: str | None = typer.Option(None, "--env-file", help="override env file path"),
    host: str = typer.Option("0.0.0.0", "--host", help="bind host"),
    workers: int = typer.Option(1, "--workers", help="uvicorn workers"),
    reload: bool = typer.Option(False, "--reload", help="enable autoreload"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_path = Path(env_file).expanduser() if env_file else paths["env"]
    if not env_path.exists():
        print(f"missing env file: {env_path}")
        print("run: python connectors/filesystem/local/filesystem_local.py init")
        raise typer.Exit(code=1)

    try:
        spec = _service_spec(state_dir, port=port, host=host, workers=workers, reload=reload)
    except RuntimeError as exc:
        print(str(exc))
        raise typer.Exit(code=1)
    pid = _pid_from_file(spec.pidfile)
    if _is_pid_alive(pid):
        print(f"{spec.name}: already running (pid={pid})")
        return

    child_env = _child_env(env_path)
    with spec.logfile.open("ab") as log_fp:
        proc = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=child_env,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    pid = proc.pid
    if not _wait_for_pid(pid):
        print(f"{spec.name}: failed to start, check log {spec.logfile}")
        raise typer.Exit(code=1)

    time.sleep(0.7)
    if not _is_pid_alive(pid):
        print(f"{spec.name}: exited during startup, check log {spec.logfile}")
        raise typer.Exit(code=1)

    _write_pid(spec.pidfile, pid)
    print(f"{spec.name}: started pid={pid} log={spec.logfile}")


@app.command("foreground")
def cmd_foreground(
    ctx: typer.Context,
    env_file: str | None = typer.Option(None, "--env-file", help="override env file path"),
    host: str = typer.Option("0.0.0.0", "--host", help="bind host"),
    workers: int = typer.Option(1, "--workers", help="uvicorn workers"),
    reload: bool = typer.Option(False, "--reload", help="enable autoreload"),
) -> None:
    """Run connector in foreground using local state/env (interactive debug mode)."""
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_path = Path(env_file).expanduser() if env_file else paths["env"]
    if not env_path.exists():
        print(f"missing env file: {env_path}")
        print("run: python connectors/filesystem/local/filesystem_local.py init")
        raise typer.Exit(code=1)

    try:
        spec = _service_spec(state_dir, port=port, host=host, workers=workers, reload=reload)
    except RuntimeError as exc:
        print(str(exc))
        raise typer.Exit(code=1)

    child_env = _child_env(env_path)
    rc = subprocess.run(spec.command, cwd=spec.cwd, env=child_env).returncode
    raise typer.Exit(code=rc or 0)


@app.command("stop")
def cmd_stop(
    ctx: typer.Context,
    grace_seconds: float = typer.Option(8.0, "--grace-seconds", help="shutdown grace period"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    if not _is_pid_alive(pid):
        _remove_pid(spec.pidfile)
        print(f"{spec.name}: not running")
        return

    _terminate_pid(pid, grace_seconds=grace_seconds)
    _remove_pid(spec.pidfile)
    print(f"{spec.name}: stopped")


@app.command("status")
def cmd_status(ctx: typer.Context) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    alive = _is_pid_alive(pid)
    state = "running" if alive else "stopped"
    print(f"{spec.name:20} {state:8} pid={pid if pid else '-'} log={spec.logfile}")
    if not alive:
        raise typer.Exit(code=1)


@app.command("logs")
def cmd_logs(
    ctx: typer.Context,
    lines: int = typer.Option(100, "--lines", help="tail lines"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)

    if not spec.logfile.exists():
        print(f"log not found: {spec.logfile}")
        raise typer.Exit(code=1)

    content = spec.logfile.read_text(errors="replace").splitlines()
    for line in content[-lines:]:
        print(line)


def _looks_like_app_binary() -> bool:
    argv0 = sys.argv[0] if sys.argv else ""
    return ".app/Contents/MacOS/" in argv0


def _enable_launcher_log(state_dir: Path) -> None:
    logs_dir = _state_paths(state_dir)["logs"]
    logs_dir.mkdir(parents=True, exist_ok=True)
    launcher_log = logs_dir / "launcher.log"

    fp = launcher_log.open("a", buffering=1)
    os.dup2(fp.fileno(), 1)
    os.dup2(fp.fileno(), 2)

    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] app-launch argv={sys.argv} cwd={Path.cwd()}")



if __name__ == "__main__":
    app_launch = _looks_like_app_binary() or getattr(sys, "frozen", False)
    if app_launch:
        _enable_launcher_log(DEFAULT_STATE_DIR)

    # No-args UX defaults to foreground for simple debugging.
    # App-bundle mode remains explicit background start for double-click launch.
    if len(sys.argv) == 1:
        sys.argv.append("start" if app_launch else "foreground")

    app()
