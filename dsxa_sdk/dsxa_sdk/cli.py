"""
CLI entrypoint for dsxa-sdk.

Example:
    dsxa --base-url https://scanner --token $TOKEN scan-binary --file sample.docx --metadata App123 --protected-entity 3
"""

from __future__ import annotations

import asyncio
import base64
import pathlib
import time
from dataclasses import dataclass
from typing import List, Optional

import typer
from dotenv import load_dotenv
from rich import print_json

from .client import DSXAClient, AsyncDSXAClient, ScanMode
from .models import ScanResponse
from . import config_store

# Load .env automatically so DSXA_BASE_URL / DSXA_AUTH_TOKEN etc. can be stored there.
load_dotenv()

app = typer.Typer(
    help="Command-line interface for DSX Application Scanner REST APIs.",
    no_args_is_help=True,
)
context_app = typer.Typer(help="Manage DSXA CLI contexts stored in ~/.dsxa/config.json.")
app.add_typer(context_app, name="context")


@dataclass
class CLIConfig:
    base_url: str
    auth_token: Optional[str]
    protected_entity: Optional[int]
    verify_tls: bool
    context_name: Optional[str]


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        envvar="DSXA_BASE_URL",
        help="DSXA scanner base URL including scheme (e.g., https://scanner:443). "
        "Set via flag/env or store in a context (see: dsxa context add).",
    ),
    auth_token: Optional[str] = typer.Option(
        None,
        "--token",
        envvar="DSXA_AUTH_TOKEN",
        help="Auth token (Bearer). Optional when DSXA accepts anonymous requests. "
        "Set via flag/env or store in a context.",
    ),
    protected_entity: Optional[int] = typer.Option(
        None,
        "--protected-entity",
        envvar="DSXA_PROTECTED_ENTITY",
        help="Protected entity ID header. Falls back to context value or 1.",
    ),
    verify_tls: Optional[bool] = typer.Option(
        None,
        "--verify-tls/--no-verify-tls",
        envvar="DSXA_VERIFY_TLS",
        help="Verify TLS certificates (default true).",
    ),
    context_name: Optional[str] = typer.Option(
        None,
        "--context",
        envvar="DSXA_CONTEXT",
        help="Context/profile name from ~/.dsxa/config.json to use for defaults.",
    ),
):
    """
    Capture shared CLI options / environment configuration.
    """
    if ctx.invoked_subcommand is None and ctx.resilient_parsing:
        return

    cfg_file = config_store.load_config()
    selected_context = context_name or cfg_file.get("current")
    profile = config_store.get_context(cfg_file, selected_context)
    if context_name and not profile:
        typer.echo(
            f"Context '{context_name}' not found in {config_store.CONFIG_PATH}. "
            "Proceeding without it.",
            err=True,
        )

    resolved_base_url = base_url or (profile or {}).get("base_url")
    if not resolved_base_url:
        typer.echo(
            "Base URL is required. Provide --base-url / DSXA_BASE_URL or set a context via 'dsxa context add'.",
            err=True,
        )
        raise typer.Exit(code=1)

    resolved_auth_token = auth_token if auth_token is not None else (profile or {}).get("auth_token")
    resolved_protected_entity = protected_entity
    if resolved_protected_entity is None:
        resolved_protected_entity = (profile or {}).get("protected_entity", 1)
    resolved_verify_tls = verify_tls if verify_tls is not None else (profile or {}).get("verify_tls", True)

    ctx.obj = CLIConfig(
        base_url=resolved_base_url.rstrip("/"),
        auth_token=resolved_auth_token,
        protected_entity=int(resolved_protected_entity) if resolved_protected_entity is not None else 1,
        verify_tls=bool(resolved_verify_tls),
        context_name=selected_context,
    )


def get_client(ctx: typer.Context) -> DSXAClient:
    cfg: CLIConfig = ctx.obj
    return DSXAClient(
        base_url=cfg.base_url,
        auth_token=cfg.auth_token,
        default_protected_entity=cfg.protected_entity,
        verify_tls=cfg.verify_tls,
    )


@app.command("scan-binary")
def scan_binary(
    ctx: typer.Context,
    file: pathlib.Path = typer.Argument(..., exists=True, readable=True, help="Path to the file to scan"),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password", help="Password for encrypted file"),
    base64_header: bool = typer.Option(False, "--base64-header", help="Send via binary endpoint with X-Content-Type: base64"),
):
    """Submit a file in binary mode."""
    client = get_client(ctx)
    with file.open("rb") as fh:
        resp = client.scan_binary(fh.read(), custom_metadata=custom_metadata, password=password, base64_header=base64_header)
    print_scan_response(resp)
    client.close()


@app.command("scan-base64")
def scan_base64(
    ctx: typer.Context,
    file: pathlib.Path = typer.Argument(..., exists=True, readable=True),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password"),
):
    """Submit a file encoded to base64."""
    client = get_client(ctx)
    with file.open("rb") as fh:
        encoded = base64.b64encode(fh.read())
    resp = client.scan_base64(encoded, custom_metadata=custom_metadata, password=password)
    print_scan_response(resp)
    client.close()


@app.command("scan-file")
def scan_file(
    ctx: typer.Context,
    file: pathlib.Path = typer.Argument(..., exists=True, readable=True),
    mode: ScanMode = typer.Option(ScanMode.BINARY, "--mode", case_sensitive=False),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password"),
):
    """Convenience command (auto base64 encoding when mode=base64)."""
    client = get_client(ctx)
    resp = client.scan_file(str(file), mode=mode, custom_metadata=custom_metadata, password=password)
    print_scan_response(resp)
    client.close()


@app.command("scan-hash")
def scan_hash(
    ctx: typer.Context,
    hash_value: str = typer.Option(..., "--hash", help="SHA256 hash to submit"),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
):
    """Submit a hash for reputation scanning."""
    client = get_client(ctx)
    resp = client.scan_hash(hash_value, custom_metadata=custom_metadata)
    print_scan_response(resp)
    client.close()


@app.command("scan-by-path")
def scan_by_path(
    ctx: typer.Context,
    stream_path: str = typer.Option(..., "--stream-path", help="Remote path (Stream-Path header value)"),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password"),
    poll: bool = typer.Option(True, "--poll/--no-poll", help="Poll /result/by_path until verdict != Scanning"),
    interval: float = typer.Option(5.0, "--interval", help="Polling interval seconds"),
    timeout: float = typer.Option(900.0, "--timeout", help="Polling timeout seconds"),
):
    """Initiate scan-by-path and optionally poll until verdict ready."""
    client = get_client(ctx)
    submit = client.scan_by_path(stream_path, custom_metadata=custom_metadata, password=password)
    typer.echo(f"Submitted scan_guid={submit.scan_guid}, verdict={submit.verdict}")
    if poll:
        verdict = client.poll_scan_by_path(submit.scan_guid, interval_seconds=interval, timeout_seconds=timeout)
        print_scan_response(verdict)
    client.close()


@app.command("result-by-path")
def result_by_path(
    ctx: typer.Context,
    scan_guid: str = typer.Argument(..., help="Scan GUID returned from scan-by-path"),
    poll: bool = typer.Option(False, "--poll/--no-poll", help="Poll until verdict != Scanning"),
    interval: float = typer.Option(5.0, "--interval", help="Polling interval seconds"),
    timeout: float = typer.Option(900.0, "--timeout", help="Polling timeout seconds"),
):
    """Fetch the latest verdict for a scan-by-path submission."""
    client = get_client(ctx)
    if poll:
        resp = client.poll_scan_by_path(scan_guid, interval_seconds=interval, timeout_seconds=timeout)
    else:
        resp = client.get_scan_by_path_result(scan_guid)
    print_scan_response(resp)
    client.close()


@app.command("scan-files")
def scan_files(
    ctx: typer.Context,
    files: List[pathlib.Path] = typer.Argument(..., readable=True, exists=True),
    mode: ScanMode = typer.Option(ScanMode.BINARY, "--mode", case_sensitive=False),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password"),
    concurrency: int = typer.Option(5, "--concurrency", min=1),
):
    """
    Scan one or more explicit file paths concurrently using the async client.
    Example:
        dsxa scan-files dsxa_sdk/tests/assets/samples/* --concurrency 4
    """
    if not files:
        typer.echo("No files specified", err=True)
        raise typer.Exit(code=1)
    asyncio.run(
        _scan_paths(
            ctx,
            files,
            mode=mode,
            custom_metadata=custom_metadata,
            password=password,
            concurrency=concurrency,
        )
    )


@app.command("scan-folder")
def scan_folder(
    ctx: typer.Context,
    folder: pathlib.Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    pattern: str = typer.Option("**/*", "--pattern", help="Glob pattern relative to folder."),
    mode: ScanMode = typer.Option(ScanMode.BINARY, "--mode", case_sensitive=False),
    custom_metadata: Optional[str] = typer.Option(None, "--metadata"),
    password: Optional[str] = typer.Option(None, "--password"),
    concurrency: int = typer.Option(5, "--concurrency", min=1),
):
    """
    Scan all files under a folder (matching the given glob pattern) using the async client.
    Examples:
        dsxa scan-folder dsxa_sdk/tests/assets/samples --pattern "**/*"
        dsxa scan-folder ./samples --pattern "**/*.pdf" --concurrency 8
    """
    if not folder.is_dir():
        typer.echo(f"{folder} is not a directory", err=True)
        raise typer.Exit(code=1)
    files = [p for p in folder.glob(pattern) if p.is_file()]
    if not files:
        typer.echo("No files matched the provided pattern", err=True)
        raise typer.Exit(code=1)
    asyncio.run(
        _scan_paths(
            ctx,
            files,
            mode=mode,
            custom_metadata=custom_metadata,
            password=password,
            concurrency=concurrency,
        )
    )


async def _scan_paths(
    ctx: typer.Context,
    paths: List[pathlib.Path],
    *,
    mode: ScanMode,
    custom_metadata: Optional[str],
    password: Optional[str],
    concurrency: int,
):
    client = get_async_client(ctx)
    sem = asyncio.Semaphore(max(1, concurrency))
    start = time.perf_counter()
    success = 0
    failures = 0

    async def process(path: pathlib.Path):
        nonlocal success, failures
        async with sem:
            try:
                data = await asyncio.to_thread(path.read_bytes)
                resp = await client.scan_binary(
                    data,
                    custom_metadata=custom_metadata,
                    password=password,
                    base64_header=(mode == ScanMode.BASE64),
                )
                typer.echo(f"{path}: {resp.verdict.value} (scan_guid={resp.scan_guid})")
                success += 1
            except Exception as exc:  # pragma: no cover - CLI helper
                failures += 1
                typer.echo(f"{path}: ERROR {exc}", err=True)

    await asyncio.gather(*(process(p) for p in paths))
    await client.aclose()
    elapsed = time.perf_counter() - start
    typer.echo(
        f"Processed {len(paths)} file(s) in {elapsed:.2f}s "
        f"(scanned={success}, errors={failures})"
    )

@context_app.command("list")
def context_list():
    """List available contexts and show the current selection."""
    cfg = config_store.load_config()
    current = cfg.get("current")
    contexts = cfg.get("contexts", {})
    if not contexts:
        typer.echo("No contexts configured. Add one with: dsxa context add")
        return
    for name, profile in contexts.items():
        marker = "*" if name == current else " "
        base = profile.get("base_url", "<missing>")
        typer.echo(f"{marker} {name}: {base}")


@context_app.command("set")
def context_set(name: str = typer.Argument(..., help="Context name to activate")):
    """Set the current context."""
    cfg = config_store.load_config()
    if name not in cfg.get("contexts", {}):
        typer.echo(f"Context '{name}' not found. Add it first with: dsxa context add {name}", err=True)
        raise typer.Exit(code=1)
    config_store.set_current(cfg, name)
    config_store.save_config(cfg)
    typer.echo(f"Current context set to '{name}'.")


@context_app.command("add")
def context_add(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Name for the new context"),
):
    """Interactively add a context to ~/.dsxa/config.json."""
    cfg = config_store.load_config()
    ctx_name = name or typer.prompt("Context name", default="default")

    base_url = typer.prompt("Base URL (e.g., https://scanner:443)")
    auth_token = typer.prompt("Auth token (leave blank if not required)", default="", hide_input=True)
    protected_entity = typer.prompt("Protected entity (integer, blank for 1)", default="")
    verify_tls = typer.confirm("Verify TLS certificates?", default=True)

    profile = {
        "base_url": base_url.rstrip("/"),
        "auth_token": auth_token if auth_token else None,
        "protected_entity": int(protected_entity) if str(protected_entity).strip() else 1,
        "verify_tls": verify_tls,
    }
    config_store.set_context(cfg, ctx_name, profile)

    should_set_current = cfg.get("current") is None or typer.confirm(
        f"Set '{ctx_name}' as the current context?", default=True
    )
    if should_set_current:
        config_store.set_current(cfg, ctx_name)

    config_store.save_config(cfg)
    typer.echo(f"Context '{ctx_name}' saved to {config_store.CONFIG_PATH}.")


def print_scan_response(resp: ScanResponse):
    print_json(data=resp.model_dump(by_alias=True))


def get_async_client(ctx: typer.Context) -> AsyncDSXAClient:
    cfg: CLIConfig = ctx.obj
    return AsyncDSXAClient(
        base_url=cfg.base_url,
        auth_token=cfg.auth_token,
        default_protected_entity=cfg.protected_entity,
        verify_tls=cfg.verify_tls,
    )
