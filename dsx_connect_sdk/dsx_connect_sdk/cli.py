from __future__ import annotations

import json
from typing import Optional

import typer

from .client import DiannaApiClient
from .exceptions import DiannaApiError

app = typer.Typer(help="CLI for DSX-Connect DIANNA APIs")


def _print_json(payload) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


@app.callback()
def main(
    ctx: typer.Context,
    base_url: str = typer.Option("http://127.0.0.1:8586", help="DSX-Connect base URL"),
    timeout: float = typer.Option(20.0, help="HTTP timeout seconds"),
) -> None:
    ctx.obj = {"client": DiannaApiClient(base_url=base_url, timeout=timeout)}


@app.command("analyze-from-siem")
def analyze_from_siem(
    ctx: typer.Context,
    scan_request_task_id: Optional[str] = typer.Option(None),
    connector_uuid: Optional[str] = typer.Option(None),
    connector_url: Optional[str] = typer.Option(None),
    location: Optional[str] = typer.Option(None),
    metainfo: Optional[str] = typer.Option(None),
    archive_password: Optional[str] = typer.Option(None),
) -> None:
    client: DiannaApiClient = ctx.obj["client"]
    try:
        res = client.analyze_from_siem(
            scan_request_task_id=scan_request_task_id,
            connector_uuid=connector_uuid,
            connector_url=connector_url,
            location=location,
            metainfo=metainfo,
            archive_password=archive_password,
        )
        _print_json(res)
    except DiannaApiError as exc:
        typer.echo(str(exc), err=True)
        if exc.payload is not None:
            _print_json(exc.payload)
        raise typer.Exit(code=1)


@app.command("get-result")
def get_result(
    ctx: typer.Context,
    analysis_id: Optional[str] = typer.Option(None, "--analysis-id", "--analyis-id"),
    dianna_analysis_task_id: Optional[str] = typer.Option(
        None, "--dianna-analysis-task-id", "--task-id"
    ),
    attempts: int = typer.Option(1, min=1),
    sleep_seconds: float = typer.Option(2.0, min=0.0),
) -> None:
    client: DiannaApiClient = ctx.obj["client"]
    if not analysis_id and not dianna_analysis_task_id:
        raise typer.BadParameter("Provide --analysis-id or --dianna-analysis-task-id.")
    if analysis_id and dianna_analysis_task_id:
        raise typer.BadParameter("Provide only one of --analysis-id or --dianna-analysis-task-id.")

    try:
        if analysis_id:
            if attempts > 1:
                res = client.poll_result(analysis_id, attempts=attempts, sleep_seconds=sleep_seconds)
            else:
                res = client.get_result(analysis_id)
        else:
            if attempts > 1:
                res = client.poll_result_by_task_id(
                    dianna_analysis_task_id,
                    attempts=attempts,
                    sleep_seconds=sleep_seconds,
                )
            else:
                res = client.get_result_by_task_id(dianna_analysis_task_id)
        _print_json(res)
    except DiannaApiError as exc:
        typer.echo(str(exc), err=True)
        if exc.payload is not None:
            _print_json(exc.payload)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
