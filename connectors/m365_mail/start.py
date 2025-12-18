import typer
import uvicorn
from shared.dsx_logging import dsx_logging

# Ensure connector is registered via decorators
import connectors.m365_mail.m365_mail_connector  # noqa: F401
from connectors.m365_mail.config import config as _cfg

app = typer.Typer(help="Start the M365 Mail Connector.")


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind the FastAPI server."),
    port: int = typer.Option(8650, help="Port to bind the FastAPI server."),
    reload: bool = typer.Option(False, help="Enable autoreload (development only)."),
    workers: int = typer.Option(1, help="Number of Uvicorn worker processes.")
):
    dsx_logging.info(
        f"Starting M365 Mail Connector on {host}:{port} "
        f"(reload={'on' if reload else 'off'}, workers={workers})"
    )
    ssl_kwargs = {}
    if _cfg.use_tls and _cfg.tls_certfile and _cfg.tls_keyfile:
        ssl_kwargs = {"ssl_certfile": _cfg.tls_certfile, "ssl_keyfile": _cfg.tls_keyfile}

    uvicorn.run(
        "connectors.framework.dsx_connector:connector_api",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        **ssl_kwargs
    )


if __name__ == "__main__":
    app()

