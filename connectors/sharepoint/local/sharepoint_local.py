#!/usr/bin/env python3
"""Run SharePoint connector locally without Docker/K8s."""

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


DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local" / "sharepoint-connector"
DEFAULT_PORT = 8640

app = typer.Typer(help="SharePoint connector local runtime manager")


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    pidfile: Path
    cwd: Path


def _is_sharepoint_repo_root(path: Path) -> bool:
    return (path / "connectors" / "sharepoint" / "start.py").exists()


def _repo_root() -> Path:
    override = os.getenv("DSXCONNECT_LOCAL_REPO_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if _is_sharepoint_repo_root(p):
            return p
        raise RuntimeError(f"DSXCONNECT_LOCAL_REPO_ROOT is set but invalid: {p}")

    source_guess = Path(__file__).resolve().parents[3]
    if _is_sharepoint_repo_root(source_guess):
        return source_guess

    if getattr(sys, "frozen", False):
        exe = Path(sys.argv[0]).resolve()
        if len(exe.parents) >= 6:
            app_guess = exe.parents[5]
            if _is_sharepoint_repo_root(app_guess):
                return app_guess

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if _is_sharepoint_repo_root(candidate):
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
    return f"""# SharePoint connector local runtime env (generated)

LOG_LEVEL=debug
DSXCONNECTOR_APP_ENV=dev

# Connector endpoints
DSXCONNECTOR_CONNECTOR_URL=http://127.0.0.1:{port}
DSXCONNECTOR_DSX_CONNECT_URL=http://127.0.0.1:8586

# Optional auth
DSXCONNECTOR_AUTH__ENABLED=false
#DSXCONNECT_ENROLLMENT_TOKEN=abc123

# SharePoint target (either ASSET URL or host/site fields)
DSXCONNECTOR_ASSET=
DSXCONNECTOR_FILTER=

# Microsoft Graph app auth
SP_TENANT_ID=
SP_CLIENT_ID=
SP_CLIENT_SECRET=

# Optional explicit site targeting (used when ASSET is not a full URL)
DSXCONNECTOR_SP_HOSTNAME=
DSXCONNECTOR_SP_SITE_PATH=
DSXCONNECTOR_SP_DRIVE_NAME=Shared Documents

# Item actions
DSXCONNECTOR_ITEM_ACTION=nothing
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=dsxconnect-quarantine

# Optional webhook mode
SP_WEBHOOK_ENABLED=false
SP_WEBHOOK_URL=

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
        str(repo / "connectors" / "sharepoint" / "start.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        str(workers),
        "--reload" if reload else "--no-reload",
    ]

    return ServiceSpec(
        name="sharepoint-connector",
        command=cmd,
        logfile=paths["logs"] / "sharepoint-connector.log",
        pidfile=paths["run"] / "sharepoint-connector.pid",
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
    prompt_credentials: bool = typer.Option(True, "--prompt-credentials/--no-prompt-credentials", help="prompt for tenant/client credentials"),
    tenant_id: str | None = typer.Option(None, "--tenant-id", help="SharePoint tenant ID"),
    client_id: str | None = typer.Option(None, "--client-id", help="Azure app client ID"),
    client_secret: str | None = typer.Option(None, "--client-secret", help="Azure app client secret"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    paths = _ensure_dirs(state_dir)
    env_file = paths["env"]

    if env_file.exists() and not force:
        print(f"env exists: {env_file}")
    else:
        env_file.write_text(_default_env_template(state_dir=state_dir, port=port))
        print(f"wrote env template: {env_file}")

    current = _read_env_map(env_file)
    vals = {
        "SP_TENANT_ID": tenant_id if tenant_id is not None else current.get("SP_TENANT_ID", current.get("DSXCONNECTOR_SP_TENANT_ID", "")),
        "SP_CLIENT_ID": client_id if client_id is not None else current.get("SP_CLIENT_ID", current.get("DSXCONNECTOR_SP_CLIENT_ID", "")),
        "SP_CLIENT_SECRET": client_secret if client_secret is not None else current.get("SP_CLIENT_SECRET", current.get("DSXCONNECTOR_SP_CLIENT_SECRET", "")),
    }

    if prompt_credentials and sys.stdin.isatty():
        vals["SP_TENANT_ID"] = typer.prompt(
            "SharePoint Tenant ID",
            default=vals["SP_TENANT_ID"],
            show_default=bool(vals["SP_TENANT_ID"]),
        ).strip()
        vals["SP_CLIENT_ID"] = typer.prompt(
            "SharePoint Client ID",
            default=vals["SP_CLIENT_ID"],
            show_default=bool(vals["SP_CLIENT_ID"]),
        ).strip()
        vals["SP_CLIENT_SECRET"] = typer.prompt(
            "SharePoint Client Secret",
            default=vals["SP_CLIENT_SECRET"],
            hide_input=True,
            show_default=False,
        ).strip()

    _upsert_env_values(env_file, vals)
    print(f"updated credentials in: {env_file}")
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
        env_path.write_text(_default_env_template(state_dir=state_dir, port=port))
        print(f"created default env: {env_path}")

    spec = _service_spec(state_dir, port=port, host=host, workers=workers, reload=reload)
    existing = _pid_from_file(spec.pidfile)
    if _is_pid_alive(existing):
        print(f"{spec.name}: already running (pid={existing})")
        raise typer.Exit(code=0)

    child_env = _child_env(env_path)
    spec.logfile.parent.mkdir(parents=True, exist_ok=True)
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
        raise RuntimeError(f"{spec.name}: failed to start")

    time.sleep(0.8)
    if not _is_pid_alive(pid):
        tail = ""
        try:
            tail = "\n".join(spec.logfile.read_text(errors="replace").splitlines()[-40:])
        except Exception:
            pass
        raise RuntimeError(f"{spec.name}: exited during startup\n{tail}")

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
        env_path.write_text(_default_env_template(state_dir=state_dir, port=port))
        print(f"created default env: {env_path}")

    spec = _service_spec(state_dir, port=port, host=host, workers=workers, reload=reload)
    child_env = _child_env(env_path)
    rc = subprocess.run(spec.command, cwd=spec.cwd, env=child_env).returncode
    raise typer.Exit(code=rc or 0)


@app.command("stop")
def cmd_stop(ctx: typer.Context) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    if not _is_pid_alive(pid):
        _remove_pid(spec.pidfile)
        print(f"{spec.name}: not running")
        return
    _terminate_pid(pid, grace_seconds=8.0)
    _remove_pid(spec.pidfile)
    print(f"{spec.name}: stopped")


@app.command("status")
def cmd_status(ctx: typer.Context) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)
    pid = _pid_from_file(spec.pidfile)
    alive = _is_pid_alive(pid)
    state = "running" if alive else "stopped"
    print(f"{spec.name} {state:8} pid={pid or '-'} log={spec.logfile}")


@app.command("logs")
def cmd_logs(
    ctx: typer.Context,
    lines: int = typer.Option(120, "--lines", help="tail lines"),
    follow: bool = typer.Option(False, "--follow", help="follow log output"),
) -> None:
    state_dir, port = _ctx_values(ctx)
    spec = _service_spec(state_dir, port=port, host="0.0.0.0", workers=1, reload=False)
    if not spec.logfile.exists():
        print(f"log file not found: {spec.logfile}")
        raise typer.Exit(code=0)

    content = spec.logfile.read_text(errors="replace").splitlines()
    tail = content[-lines:] if lines > 0 else content
    for line in tail:
        print(line)

    if not follow:
        return

    print("-- follow mode (Ctrl+C to stop) --")
    with spec.logfile.open("r", errors="replace") as fp:
        fp.seek(0, os.SEEK_END)
        try:
            while True:
                line = fp.readline()
                if line:
                    print(line, end="")
                else:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("foreground")
    app()
