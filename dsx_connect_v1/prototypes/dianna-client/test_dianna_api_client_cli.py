#!/usr/bin/env python3
"""CLI test harness for dsx_connect_sdk."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import typer

ROOT = Path(__file__).resolve().parents[3]
SDK_SRC = ROOT / "dsx_connect_sdk"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

from dsx_connect_sdk import DiannaApiClient, DiannaApiError

app = typer.Typer(help="Test CLI for DSX-Connect DIANNA API client")


def _print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def _poll_by_task_with_progress(
    client: DiannaApiClient,
    dianna_analysis_task_id: str,
    *,
    attempts: int,
    sleep_seconds: float,
) -> tuple[dict, bool]:
    attempts = max(1, int(attempts))
    sleep_seconds = max(0.0, float(sleep_seconds))
    last: dict = {}
    printed = False
    spinner_chars = "|/-\\"
    spinner_idx = 0

    for i in range(1, attempts + 1):
        result = client.get_result_by_task_id(dianna_analysis_task_id)
        last = result
        status = str(result.get("status", "")).lower()
        if status in {"success", "accepted"}:
            return result, printed
        if i < attempts:
            ch = spinner_chars[spinner_idx % len(spinner_chars)]
            typer.echo(f"\rwaiting {ch}", nl=False)
            spinner_idx += 1
            printed = True
            time.sleep(sleep_seconds)

    return last, printed


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
    except DiannaApiError as e:
        typer.echo(str(e), err=True)
        if e.payload is not None:
            _print_json(e.payload)
        raise typer.Exit(code=1)


@app.command("analyze")
def analyze_and_wait(
    ctx: typer.Context,
    scan_request_task_id: Optional[str] = typer.Option(None),
    connector_uuid: Optional[str] = typer.Option(None),
    connector_url: Optional[str] = typer.Option(None),
    location: Optional[str] = typer.Option(None),
    metainfo: Optional[str] = typer.Option(None),
    archive_password: Optional[str] = typer.Option(None),
    attempts: int = typer.Option(60, min=1, help="poll attempts"),
    sleep_seconds: float = typer.Option(2.0, min=0.0, help="sleep between attempts"),
) -> None:
    client: DiannaApiClient = ctx.obj["client"]
    try:
        enqueue = client.analyze_from_siem(
            scan_request_task_id=scan_request_task_id,
            connector_uuid=connector_uuid,
            connector_url=connector_url,
            location=location,
            metainfo=metainfo,
            archive_password=archive_password,
        )
        task_id = str(enqueue.get("dianna_analysis_task_id") or enqueue.get("task_id") or "").strip()
        if not task_id:
            _print_json({"enqueue": enqueue, "message": "missing dianna_analysis_task_id in enqueue response"})
            raise typer.Exit(code=1)

        typer.echo(f"enqueued dianna_analysis_task_id={task_id}")
        result, printed = _poll_by_task_with_progress(
            client,
            task_id,
            attempts=attempts,
            sleep_seconds=sleep_seconds,
        )
        if printed:
            typer.echo("")
        _print_json({"enqueue": enqueue, "result": result})
    except DiannaApiError as e:
        typer.echo(str(e), err=True)
        if e.payload is not None:
            _print_json(e.payload)
        raise typer.Exit(code=1)


@app.command("get-result")
def get_result(
    ctx: typer.Context,
    analysis_id: Optional[str] = typer.Option(None, "--analysis-id", "--analyis-id"),
    dianna_analysis_task_id: Optional[str] = typer.Option(None, "--dianna-analysis-task-id", "--task-id"),
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
                    dianna_analysis_task_id, attempts=attempts, sleep_seconds=sleep_seconds
                )
            else:
                res = client.get_result_by_task_id(dianna_analysis_task_id)
        _print_json(res)
    except DiannaApiError as e:
        typer.echo(str(e), err=True)
        if e.payload is not None:
            _print_json(e.payload)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
