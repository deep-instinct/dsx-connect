#!/usr/bin/env python3
"""Run M365 Mail connector locally without Docker/K8s."""

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


DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local" / "m365-mail-connector"
DEFAULT_PORT = 8650

app = typer.Typer(help="M365 Mail connector local runtime manager")


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    pidfile: Path
    cwd: Path


def _is_repo_root(path: Path) -> bool:
    return (path / "connectors" / "m365_mail" / "start.py").exists()


def _repo_root() -> Path:
    override = os.getenv("DSXCONNECT_LOCAL_REPO_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if _is_repo_root(p):
            return p
        raise RuntimeError(f"DSXCONNECT_LOCAL_REPO_ROOT is set but invalid: {p}")

    source_guess = Path(__file__).resolve().parents[3]
    if _is_repo_root(source_guess):
        return source_guess

    if getattr(sys, "frozen", False):
        exe = Path(sys.argv[0]).resolve()
        if len(exe.parents) >= 6:
            app_guess = exe.parents[5]
            if _is_repo_root(app_guess):
                return app_guess

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _is_repo_root(candidate):
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
        "env": state_dir / ".env.local",
    }


def _ensure_dirs(state_dir: Path) -> Dict[str, Path]:
    paths = _state_paths(state_dir)
    for key in ("root", "logs", "run", "data"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _default_env_template(*, state_dir: Path, port: int) -> str:
    _ = state_dir
    return f"""# M365 Mail connector local runtime env (generated)

LOG_LEVEL=debug
DSXCONNECTOR_APP_ENV=dev

# Connector endpoints
DSXCONNECTOR_CONNECTOR_URL=http://127.0.0.1:{port}
DSXCONNECTOR_DSX_CONNECT_URL=http://127.0.0.1:8586

# Optional auth
DSXCONNECTOR_AUTH__ENABLED=false
#DSXCONNECT_ENROLLMENT_TOKEN=abc123

# M365 Graph auth / scope
DSXCONNECTOR_M365_TENANT_ID=
DSXCONNECTOR_M365_CLIENT_ID=
DSXCONNECTOR_M365_CLIENT_SECRET=
DSXCONNECTOR_M365_MAILBOX_UPNS=
DSXCONNECTOR_ASSET=
DSXCONNECTOR_FILTER=

# Item actions
DSXCONNECTOR_ITEM_ACTION=nothing
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=dsxconnect-quarantine

# Optional webhook mode
DSXCONNECTOR_M365_WEBHOOK_URL=
DSXCONNECTOR_M365_CLIENT_STATE=

# Optional TLS
DSXCONNECTOR_USE_TLS=false
"""


def _read_env_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _upsert_env_values(path: Path, values: dict[str, str]) -> None:
    existing_lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    keys = set(values.keys())
    written: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        k, _ = line.split("=", 1)
        key = k.strip()
        if key in keys:
            new_lines.append(f"{key}={values[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    for key in keys:
        if key not in written:
            new_lines.append(f"{key}={values[key]}")

    if new_lines and new_lines[-1] != "":
        new_lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(new_lines))


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
        str(repo / "connectors" / "m365_mail" / "start.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--reload" if reload else "--no-reload",
    ]

    return ServiceSpec(
        name="m365-mail-connector",
        command=cmd,
        logfile=paths["logs"] / "m365-mail-connector.log",
        pidfile=paths["run"] / "m365-mail-connector.pid",
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


@app.command()
def init(ctx: typer.Context) -> None:
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    if not paths["env"].exists():
        paths["env"].write_text(_default_env_template(state_dir=state_dir, port=port))
        typer.echo(f"Created {paths['env']}")
    else:
        env_map = _read_env_map(paths["env"])
        if env_map.get("DSXCONNECTOR_CONNECTOR_URL") != f"http://127.0.0.1:{port}":
            _upsert_env_values(paths["env"], {"DSXCONNECTOR_CONNECTOR_URL": f"http://127.0.0.1:{port}"})
    typer.echo(f"State dir initialized at {state_dir}")


@app.command()
def start(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host", help="bind host"),
    workers: int = typer.Option(1, "--workers", help="uvicorn workers"),
    reload: bool = typer.Option(False, "--reload/--no-reload", help="enable autoreload"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    if not paths["env"].exists():
        paths["env"].write_text(_default_env_template(state_dir=state_dir, port=port))

    spec = _service_spec(state_dir, port=port, host=host, workers=workers, reload=reload)
    pid = _pid_from_file(spec.pidfile)
    if _is_pid_alive(pid):
        typer.echo(f"{spec.name} already running (pid={pid})")
        raise typer.Exit(0)

    with spec.logfile.open("ab") as logfp:
        proc = subprocess.Popen(
            spec.command,
            cwd=str(spec.cwd),
            env=_child_env(paths["env"]),
            stdout=logfp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    _write_pid(spec.pidfile, proc.pid)
    if not _wait_for_pid(proc.pid):
        _remove_pid(spec.pidfile)
        raise RuntimeError(f"Failed to start {spec.name}")

    typer.echo(f"Started {spec.name} (pid={proc.pid})")


@app.command()
def stop(ctx: typer.Context) -> None:
    state_dir, _ = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=DEFAULT_PORT, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    if not _is_pid_alive(pid):
        _remove_pid(spec.pidfile)
        typer.echo(f"{spec.name} is not running")
        raise typer.Exit(0)

    _terminate_pid(pid)
    _remove_pid(spec.pidfile)
    typer.echo(f"Stopped {spec.name}")


@app.command()
def status(ctx: typer.Context) -> None:
    state_dir, _ = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=DEFAULT_PORT, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    if _is_pid_alive(pid):
        typer.echo(f"{spec.name} running (pid={pid})")
        return
    _remove_pid(spec.pidfile)
    typer.echo(f"{spec.name} stopped")


if __name__ == "__main__":
    app()
