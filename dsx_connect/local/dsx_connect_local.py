#!/usr/bin/env python3
"""Run DSX-Connect core services locally without Docker/K8s."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import typer


DEFAULT_STATE_DIR = Path.home() / ".dsx-connect-local" / "dsx-connect-desktop"

app = typer.Typer(help="DSX-Connect core local runtime manager")


@dataclass
class ServiceSpec:
    name: str
    command: list[str]
    logfile: Path
    pidfile: Path
    cwd: Path
    env: Dict[str, str]


def _is_repo_root(path: Path) -> bool:
    return (path / "dsx_connect" / "dsx-connect-api-start.py").exists()


def _repo_root() -> Path:
    override = os.getenv("DSXCONNECT_LOCAL_REPO_ROOT", "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if _is_repo_root(p):
            return p
        raise RuntimeError(f"DSXCONNECT_LOCAL_REPO_ROOT is set but invalid: {p}")

    source_guess = Path(__file__).resolve().parents[2]
    if _is_repo_root(source_guess):
        return source_guess

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
    candidates.append(str(repo / ".venv" / "Scripts" / "python.exe"))

    py3 = shutil.which("python3")
    if py3:
        candidates.append(py3)
    py = shutil.which("python")
    if py:
        candidates.append(py)

    for candidate in candidates:
        if candidate and Path(candidate).exists() and os.access(candidate, os.X_OK):
            return candidate

    raise RuntimeError(
        "No usable Python interpreter found for launching core services. "
        "Set DSXCONNECT_LOCAL_PYTHON or ensure .venv/bin/python exists."
    )


def _redis_server_binary() -> str:
    override = os.getenv("DSXCONNECT_LOCAL_REDIS_SERVER", "").strip()
    if override:
        if Path(override).exists() and os.access(override, os.X_OK):
            return override
        raise RuntimeError(f"DSXCONNECT_LOCAL_REDIS_SERVER is set but invalid: {override}")
    found = shutil.which("redis-server")
    if found:
        return found
    raise RuntimeError(
        "redis-server was not found on PATH. Install Redis locally or set "
        "DSXCONNECT_LOCAL_REDIS_SERVER=/path/to/redis-server"
    )


def _state_paths(state_dir: Path) -> Dict[str, Path]:
    return {
        "root": state_dir,
        "logs": state_dir / "logs",
        "run": state_dir / "run",
        "env": state_dir / ".env.local",
    }


def _ensure_dirs(state_dir: Path) -> Dict[str, Path]:
    paths = _state_paths(state_dir)
    for key in ("root", "logs", "run"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def _default_env_template() -> str:
    return """# DSX-Connect local runtime env (generated)
# Edit scanner URL/token and optional DIANNA settings as needed.

LOG_LEVEL=debug

# DSXA scanner endpoint
DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://127.0.0.1:15000/scan/binary/v2
DSXCONNECT_SCANNER__AUTH_TOKEN=

# Local Redis layout (single redis process, separate DB indexes)
DSXCONNECT_REDIS_URL=redis://127.0.0.1:6380/3
DSXCONNECT_RESULTS_DB=redis://127.0.0.1:6380/3
DSXCONNECT_RESULTS_DB__RETAIN=1000
DSXCONNECT_WORKERS__BROKER=redis://127.0.0.1:6380/5
DSXCONNECT_WORKERS__BACKEND=redis://127.0.0.1:6380/6

# Local API transport
DSXCONNECT_USE_TLS=false

# Optional auth
DSXCONNECT_AUTH__ENABLED=false
DSXCONNECT_AUTH__ENROLLMENT_TOKEN=abc123

# Optional DIANNA
DSXCONNECT_DIANNA__ENABLED=false
DSXCONNECT_DIANNA__AUTO_ON_MALICIOUS=false
DSXCONNECT_DIANNA__INDEX_DATABASE_LOC=redis://127.0.0.1:6380/4

# Persist UI-driven core config edits only for local runtime
DSXCONNECT_CONFIG_PERSIST_LOCAL_ONLY=true

DSXCONNECT_APP_ENV=app
"""


def _read_env_file(env_path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, val = raw.split("=", 1)
        env[key.strip()] = val.strip()
    return env


def _redis_port_from_env(env_path: Path) -> int:
    env = _read_env_file(env_path)
    redis_url = env.get("DSXCONNECT_REDIS_URL", "")
    m = re.match(r"^redis://[^:/]+:(\d+)(?:/.*)?$", redis_url)
    if m:
        return int(m.group(1))
    return 6380


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


def _wait_for_pid(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_pid_alive(pid):
            return True
        time.sleep(0.1)
    return _is_pid_alive(pid)


def _terminate_pid(pid: int, grace_seconds: float = 10.0) -> None:
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


def _child_env(env_file: Path, extra: Dict[str, str] | None = None) -> Dict[str, str]:
    env = os.environ.copy()
    env["DSXCONNECT_ENV_FILE"] = str(env_file)

    repo = str(_repo_root())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo if not existing else f"{repo}:{existing}"
    if extra:
        env.update(extra)
    return env


def _service_specs(state_dir: Path, worker_pool: str, worker_concurrency: int) -> list[ServiceSpec]:
    paths = _state_paths(state_dir)
    repo = _repo_root()
    python = _runtime_python(repo)
    redis_server = _redis_server_binary()
    redis_port = _redis_port_from_env(paths["env"])
    child_env = _child_env(paths["env"])
    workers_env = _child_env(
        paths["env"],
        {
            "DSXCONNECT_WORKER_POOL": worker_pool,
            "DSXCONNECT_WORKER_CONCURRENCY": str(worker_concurrency),
        },
    )

    return [
        ServiceSpec(
            name="redis",
            command=[
                redis_server,
                "--bind",
                "127.0.0.1",
                "--port",
                str(redis_port),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            logfile=paths["logs"] / "redis.log",
            pidfile=paths["run"] / "redis.pid",
            cwd=repo,
            env=os.environ.copy(),
        ),
        ServiceSpec(
            name="api",
            command=[python, str(repo / "dsx_connect" / "dsx-connect-api-start.py")],
            logfile=paths["logs"] / "api.log",
            pidfile=paths["run"] / "api.pid",
            cwd=repo,
            env=child_env,
        ),
        ServiceSpec(
            name="workers",
            command=[python, str(repo / "dsx_connect" / "dsx-connect-workers-start.py")],
            logfile=paths["logs"] / "workers.log",
            pidfile=paths["run"] / "workers.pid",
            cwd=repo,
            env=workers_env,
        ),
    ]


def _start_one(spec: ServiceSpec) -> tuple[bool, str]:
    existing = _pid_from_file(spec.pidfile)
    if _is_pid_alive(existing):
        return True, f"{spec.name}: already running pid={existing}"
    if existing:
        _remove_pid(spec.pidfile)

    spec.logfile.parent.mkdir(parents=True, exist_ok=True)
    with spec.logfile.open("ab") as logf:
        proc = subprocess.Popen(
            spec.command,
            cwd=str(spec.cwd),
            env=spec.env,
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )

    if not _wait_for_pid(proc.pid):
        return False, f"{spec.name}: failed to start (pid did not become alive)"
    _write_pid(spec.pidfile, proc.pid)
    return True, f"{spec.name}: started pid={proc.pid} log={spec.logfile}"


def _stop_one(spec: ServiceSpec) -> tuple[bool, str]:
    pid = _pid_from_file(spec.pidfile)
    if not pid:
        return True, f"{spec.name}: not running"
    if not _is_pid_alive(pid):
        _remove_pid(spec.pidfile)
        return True, f"{spec.name}: stale pid file removed"
    _terminate_pid(pid)
    if _is_pid_alive(pid):
        return False, f"{spec.name}: failed to stop pid={pid}"
    _remove_pid(spec.pidfile)
    return True, f"{spec.name}: stopped pid={pid}"


def _ctx_state_dir(ctx: typer.Context) -> Path:
    return Path(ctx.obj["state_dir"]).expanduser()


def _ctx_worker_options(ctx: typer.Context) -> tuple[str, int]:
    return str(ctx.obj["worker_pool"]), int(ctx.obj["worker_concurrency"])


def _worker_defaults_from_env_file(state_dir: Path) -> tuple[str, int]:
    env_file = _state_paths(state_dir)["env"]
    env = _read_env_file(env_file)
    pool = str(env.get("DSXCONNECT_WORKER_POOL", "solo") or "solo").strip()
    raw_conc = str(
        env.get("DSXCONNECT_WORKER_CONCURRENCY", env.get("DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY", "1"))
    ).strip()
    try:
        conc = max(1, int(raw_conc))
    except Exception:
        conc = 1
    return pool, conc


def _inject_default_command(argv: list[str], default_command: str = "foreground") -> list[str]:
    known = {"init", "start", "stop", "status", "foreground", "--help", "-h"}
    args = list(argv)
    i = 0
    while i < len(args):
        token = args[i]
        if token in known:
            return args
        # Skip global option value.
        if token == "--state-dir":
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        # First positional token that is not a known command.
        return args
    return [*args, default_command]


def _attach_to_running_logs(specs: list[ServiceSpec]) -> None:
    print("Services already running; attaching to logs (Ctrl+C to detach).")

    stop_requested = False

    def _on_signal(signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        print(f"received signal {signum}; detaching...")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    positions: Dict[str, int] = {}
    for spec in specs:
        spec.logfile.parent.mkdir(parents=True, exist_ok=True)
        spec.logfile.touch(exist_ok=True)
        positions[spec.name] = spec.logfile.stat().st_size

    while not stop_requested:
        any_alive = False
        for spec in specs:
            pid = _pid_from_file(spec.pidfile)
            if _is_pid_alive(pid):
                any_alive = True

            try:
                with spec.logfile.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(positions.get(spec.name, 0))
                    chunk = f.read()
                    positions[spec.name] = f.tell()
            except Exception:
                chunk = ""

            if chunk:
                for line in chunk.splitlines():
                    print(f"[{spec.name}] {line}")

        if not any_alive:
            print("No managed services are running; detaching.")
            return
        time.sleep(0.25)


@app.callback()
def main(
    ctx: typer.Context,
    state_dir: str = typer.Option(str(DEFAULT_STATE_DIR), "--state-dir", help="runtime state dir"),
    worker_pool: str | None = typer.Option(
        None,
        "--worker-pool",
        help="celery worker pool (e.g. solo, prefork, threads)",
    ),
    worker_concurrency: int | None = typer.Option(
        None,
        "--worker-concurrency",
        help="celery worker concurrency",
    ),
) -> None:
    resolved_state_dir = Path(state_dir).expanduser()
    env_pool, env_conc = _worker_defaults_from_env_file(resolved_state_dir)
    resolved_pool = str(worker_pool or env_pool or "solo").strip() or "solo"
    resolved_concurrency = int(worker_concurrency if worker_concurrency is not None else env_conc)
    if resolved_concurrency < 1:
        raise typer.BadParameter("--worker-concurrency must be >= 1")

    ctx.obj = {
        "state_dir": str(resolved_state_dir),
        "worker_pool": resolved_pool,
        "worker_concurrency": resolved_concurrency,
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


@app.command("start")
def cmd_start(ctx: typer.Context) -> None:
    state_dir = _ctx_state_dir(ctx)
    worker_pool, worker_concurrency = _ctx_worker_options(ctx)
    paths = _ensure_dirs(state_dir)
    if not paths["env"].exists():
        raise typer.BadParameter(
            f"env file not found: {paths['env']} (run `init` first)"
        )
    for spec in _service_specs(state_dir, worker_pool, worker_concurrency):
        ok, msg = _start_one(spec)
        print(msg)
        if not ok:
            raise typer.Exit(code=1)


@app.command("foreground")
def cmd_foreground(ctx: typer.Context) -> None:
    state_dir = _ctx_state_dir(ctx)
    worker_pool, worker_concurrency = _ctx_worker_options(ctx)
    paths = _ensure_dirs(state_dir)
    if not paths["env"].exists():
        raise typer.BadParameter(
            f"env file not found: {paths['env']} (run `init` first)"
        )
    specs = _service_specs(state_dir, worker_pool, worker_concurrency)
    running = [s.name for s in specs if _is_pid_alive(_pid_from_file(s.pidfile))]
    if running:
        _attach_to_running_logs(specs)
        return

    children: list[tuple[ServiceSpec, subprocess.Popen]] = []
    stop_requested = False
    exit_code = 0

    def _on_signal(signum, _frame):
        nonlocal stop_requested
        stop_requested = True
        print(f"received signal {signum}; shutting down...")

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    try:
        for spec in specs:
            print(f"starting {spec.name} (foreground)")
            child = subprocess.Popen(
                spec.command,
                cwd=str(spec.cwd),
                env=spec.env,
                stdout=sys.stdout,
                stderr=sys.stderr,
                # Keep children in separate sessions so Ctrl+C is handled here,
                # then we can drain them in a controlled order.
                start_new_session=True,
            )
            children.append((spec, child))

        while not stop_requested:
            for _spec, child in children:
                rc = child.poll()
                if rc is not None:
                    exit_code = rc if rc else exit_code
                    stop_requested = True
                    break
            time.sleep(0.2)
    finally:
        # Stop in reverse startup order: workers -> api -> redis.
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

    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command("stop")
def cmd_stop(ctx: typer.Context) -> None:
    state_dir = _ctx_state_dir(ctx)
    worker_pool, worker_concurrency = _ctx_worker_options(ctx)
    _ensure_dirs(state_dir)
    # Stop in reverse dependency order.
    specs = list(reversed(_service_specs(state_dir, worker_pool, worker_concurrency)))
    exit_code = 0
    for spec in specs:
        ok, msg = _stop_one(spec)
        print(msg)
        if not ok:
            exit_code = 1
    if exit_code:
        raise typer.Exit(code=exit_code)


@app.command("status")
def cmd_status(ctx: typer.Context) -> None:
    state_dir = _ctx_state_dir(ctx)
    worker_pool, worker_concurrency = _ctx_worker_options(ctx)
    _ensure_dirs(state_dir)
    for spec in _service_specs(state_dir, worker_pool, worker_concurrency):
        pid = _pid_from_file(spec.pidfile)
        alive = _is_pid_alive(pid)
        status = "running" if alive else "stopped"
        if alive:
            print(f"{spec.name}: {status} pid={pid} log={spec.logfile}")
        else:
            print(f"{spec.name}: {status} log={spec.logfile}")


if __name__ == "__main__":
    app(_inject_default_command(sys.argv[1:]))
