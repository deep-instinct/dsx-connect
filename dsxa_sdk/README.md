# DSXA Python SDK

Lightweight Python client for Deep Instinct DSX Application Scanner (DSXA) REST APIs. Provides convenient helpers for synchronous file scans (`/scan/binary/v2`, `/scan/base64/v2`), hash scans, and the asynchronous scan-by-path workflow (`/scan/by_path` + `/result/by_path`).

## Installation

```bash
pip install dsxa-sdk
```

_Until this package is published to PyPI or an internal index, install via git/path:_

```bash
pip install /path/to/dsx-connect/dsxa_sdk
```

## License

Distributed under the GNU General Public License v3. See `LICENSE` for details.

## Testing

- Unit tests (default): `pytest tests/test_dsxa_sdk_client.py`
- Optional integration tests against a live scanner: set `DSXA_BASE_URL` and `DSXA_AUTH_TOKEN` (plus optional `DSXA_PROTECTED_ENTITY`, `DSXA_VERIFY_TLS`) and run:

```bash
DSXA_BASE_URL=https://scanner.example.com \
DSXA_AUTH_TOKEN=token \  # omit if DSXA does not require tokens
pytest tests/test_dsxa_sdk_integration.py
```

These tests submit the EICAR string and assert a valid scan GUID/verdict.

> Note: `DSXA_BASE_URL` must include the scheme (e.g., `https://scanner:443`), not just a hostname.

## Quick start

```python
from dsxa_sdk import DSXAClient, ScanMode

client = DSXAClient(
    base_url="https://scanner.example.com",
    auth_token="my-auth-token",  # optional if DSXA allows anonymous requests
    default_protected_entity=3,
    timeout=30,
)

# Binary scan (auto Content-Type + optional headers)
with open("sample.docx", "rb") as fh:
    response = client.scan_binary(
        fh.read(),
        custom_metadata="App123",
        password="password123",  # SDK encodes to base64 automatically
    )
print(response.verdict, response.file_info)

# Convenience helper for reading files + base64 endpoint
report = client.scan_file("archive.zip", mode=ScanMode.BASE64)

# Hash-only reputation request
hash_resp = client.scan_hash("e3c8ebdf74e4b7a5...")

# Scan-by-path workflow
submit = client.scan_by_path("/mnt/data/huge.tar")
verdict = client.poll_scan_by_path(submit.scan_guid, interval_seconds=10, timeout_seconds=1800)
print(verdict.verdict, verdict.verdict_details.reason)
```

## Async usage

```python
import asyncio
from dsxa_sdk import AsyncDSXAClient

async def main():
    async with AsyncDSXAClient(
        base_url="https://scanner.example.com",
        auth_token="my-auth-token",
        default_protected_entity=3,
    ) as client:
        resp = await client.scan_binary(b"data", custom_metadata="App123")
        print(resp.verdict, resp.file_info.file_type)

asyncio.run(main())
```

## CLI

Install the package (e.g., `pip install -e .`) and use the Typer-based CLI for ad-hoc scans:

```bash
# Help
dsxa --help

# Binary scan (single file, sync client)
dsxa --base-url https://scanner --token $TOKEN scan-binary --file dsxa_sdk/tests/assets/samples/BadMojoResume.pdf --metadata App123 --protected-entity 3

# Hash scan
dsxa --base-url https://scanner --token $TOKEN scan-hash --hash e3c8ebdf74e4b7a5...

# Batch scan multiple files (async client, concurrent)
dsxa --base-url https://scanner scan-files dsxa_sdk/tests/assets/samples/* --concurrency 4

# Recursively scan a folder
dsxa --base-url https://scanner scan-folder ./samples --pattern "**/*.pdf" --concurrency 8
```

Environment variables (`DSXA_BASE_URL`, optional `DSXA_AUTH_TOKEN`, optional `DSXA_PROTECTED_ENTITY` which defaults to `1`, `DSXA_VERIFY_TLS`) may be used instead of flags. If DSXA auth is disabled, simply omit `--token` / `DSXA_AUTH_TOKEN`.

You can also drop a `.env` file next to your project (the CLI loads `.env` from the current working directory upward, just like `python-dotenv`) to persist the settings:

```env
DSXA_BASE_URL=https://scanner.example.com
DSXA_AUTH_TOKEN=token  # optional
DSXA_PROTECTED_ENTITY=3  # defaults to 1 when omitted
```

### Contexts (persisted profiles)

The CLI can store multiple contexts in `~/.dsxa/config.json` (keyed under `contexts`) and fall back to the current context when flags/envs are omitted:

```bash
# Add a context (interactive prompts for base URL, token, protected entity)
dsxa context add --name default

# List and switch
dsxa context list
dsxa context set default

# Use a specific context for a single command
dsxa --context default scan-binary --file sample.pdf
```

## Distribution (PyPI or direct)

- Build artifacts: from `dsxa_sdk/` run `python -m build` to produce `dist/dsxa_sdk-<ver>-py3-none-any.whl` and `dist/dsxa_sdk-<ver>.tar.gz`.
- Publish to PyPI/TestPyPI with `python -m twine upload dist/*` (adjust repository URL for TestPyPI or private index).
- Direct/offline install: share the wheel (or both files) and install with `pip install /path/to/dsxa_sdk-<ver>-py3-none-any.whl`. For fully offline installs (including deps), pre-download deps via `pip download --dest vendor dsxa-sdk` and then install with `pip install --no-index --find-links vendor dsxa-sdk`.
- GitHub Releases (optional): when you publish a GitHub release, the workflow in `.github/workflows/release-dsxa-sdk.yml` builds the wheel/sdist and attaches them to the release. You can also trigger it manually via the `workflow_dispatch` action; if you omit a tag it will default to `dsxa-sdk-<version from pyproject.toml>`.
- Docker bundle (manual): use `.github/workflows/bundle-docker-compose.yml` to package `docker_bundle/` as a tar.gz. Trigger via workflow_dispatch; optionally provide a tag to attach it to a GitHub Release, or leave blank to just download the artifact from the run.

## Features
- Token-based authentication (Bearer header) when enabled; omit tokens for DSXA deployments that allow anonymous access.
- Optional headers: `protected_entity`, `X-Custom-Metadata`, `scan_password` (auto base64).
- Binary, base64, hash, and scan-by-path endpoints.
- Polling helper for `/result/by_path`.
- Pydantic response models for typed access to verdicts, reasons, threat types, and file info.

## Roadmap
- Async client variant.
- Automatic retries / backoff customisation.
- Integration tests and packaging to internal PyPI.
