import typer
import uvicorn
from shared.dsx_logging import dsx_logging

# Ensure connector is registered via decorators
import connectors.sharepoint.sharepoint_connector  # noqa: F401
from connectors.sharepoint.config import ConfigManager

app = typer.Typer(help="Start the Sharepoint Connector.")


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind the FastAPI server."),
    port: int = typer.Option(8640, help="Port to bind the FastAPI server."),
    reload: bool = typer.Option(False, help="Enable autoreload (development only)."),
    workers: int = typer.Option(1, help="Number of Uvicorn worker processes.")
):
    """
    Launch the Connector FastAPI app.
    """
    dsx_logging.info(
        f"Starting SharePoint Connector on {host}:{port} "
        f"(reload={'on' if reload else 'off'}, workers={workers})"
    )

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
    app()
