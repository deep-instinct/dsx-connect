import os
from pathlib import Path

import typer
import uvicorn
from shared.dsx_logging import dsx_logging

app = typer.Typer(help="Start the Filesystem Connector.")


def _resolve_local_env_file() -> Path | None:
    env_file = os.getenv("DSXCONNECTOR_ENV_FILE", "").strip()
    if env_file:
        try:
            return Path(env_file).expanduser().resolve()
        except Exception:
            return None

    for candidate in (
        Path.home() / ".dsx-connect-local" / "filesystem-connector" / ".env.local",
        Path.home() / ".dsx-connect-local" / "filesystem-connector" / ".dev.env",
    ):
        try:
            if candidate.exists():
                os.environ["DSXCONNECTOR_ENV_FILE"] = str(candidate)
                return candidate.resolve()
        except Exception:
            continue

    return None


def _enable_local_runtime_log() -> None:
    env_path = _resolve_local_env_file()
    if env_path is None or not env_path.exists():
        return

    local_root = (Path.home() / ".dsx-connect-local").resolve()
    if env_path != local_root and local_root not in env_path.parents:
        return

    logs_dir = env_path.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    logfile = logs_dir / "filesystem-connector.log"

    fp = logfile.open("a", buffering=1)
    os.dup2(fp.fileno(), 1)
    os.dup2(fp.fileno(), 2)


def _apply_local_env_overrides() -> None:
    env_path = _resolve_local_env_file()
    if env_path is None or not env_path.exists():
        return

    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, val = s.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ[key] = val
    except Exception:
        return


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind the FastAPI server."),
    port: int = typer.Option(8620, help="Port to bind the FastAPI server."),
    reload: bool = typer.Option(False, help="Enable autoreload (development only)."),
    workers: int = typer.Option(1, help="Number of Uvicorn worker processes.")
):

    """
    Launch the Filesystem Connector FastAPI app.
    """
    dsx_logging.info(
        f"Starting Filesystem Connector on {host}:{port} "
        f"(reload={'on' if reload else 'off'}, workers={workers})"
    )
    from connectors.filesystem.config import ConfigManager

    cfg = ConfigManager.reload_config()
    ssl_kwargs = {}
    if cfg.use_tls and cfg.tls_certfile and cfg.tls_keyfile:
        ssl_kwargs = {"ssl_certfile": cfg.tls_certfile, "ssl_keyfile": cfg.tls_keyfile}

    uvicorn.run(
        "connectors.framework.dsx_connector:connector_api",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        **ssl_kwargs
    )


if __name__ == "__main__":
    _enable_local_runtime_log()
    _apply_local_env_overrides()
    # Ensure connector is registered via decorators only after local env is loaded.
    import connectors.filesystem.filesystem_connector  # noqa: F401
    from connectors.filesystem.config import ConfigManager

    app()
