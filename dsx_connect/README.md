# dsx-connect · Developer Guide

This repository hosts the dsx-connect core services (FastAPI API + Celery workers) and their build tooling. The docs under `docs/` cover deployment guidance; this file is intentionally scoped to developer workflows.

## Quick Start

```bash
# optional: create a virtualenv
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
cp dsx_connect/.dev.env.example dsx_connect/.dev.env   # edit as needed
```

`dsx_connect/.dev.env` is loaded automatically by the helper scripts. Populate it with overrides such as:

```dotenv
DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://localhost:5000/scan/binary/v2
DSXCONNECT_REDIS_URL=redis://127.0.0.1:6379/3
DSXCONNECT_WORKERS__BROKER=redis://127.0.0.1:6379/5
LOG_LEVEL=debug
```

## Running the API & Workers locally

The `dsx_connect/*-start.py` scripts wrap the uvicorn / celery invocations and auto-load `.dev.env`. You can still override env vars inline when experimenting.

```bash
# API service (listens on 8586 by default)
LOG_LEVEL=debug \
DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://localhost:5000/scan/binary/v2 \
python dsx_connect/dsx-connect-api-start.py

# Celery workers (scan request + verdict + results + notification + dianna)
python dsx_connect/dsx-connect-workers-start.py
```

Each worker class can also be launched individually via:

```bash
python dsx_connect/dsx-connect-workers-start.py scan-request
python dsx_connect/dsx-connect-workers-start.py verdict
python dsx_connect/dsx-connect-workers-start.py results
python dsx_connect/dsx-connect-workers-start.py notification
python dsx_connect/dsx-connect-workers-start.py dianna
```

Common env overrides:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DSXCONNECT_SCANNER__SCAN_BINARY_URL` | DSXA endpoint used by API/workers | computed when dsxa-scanner subchart enabled; otherwise required |
| `DSXCONNECT_REDIS_URL` | Registry / results Redis | `redis://redis:6379/3` |
| `DSXCONNECT_WORKERS__BROKER` | Celery broker | `redis://redis:6379/5` |
| `DSXCONNECT_WORKERS__BACKEND` | Celery backend | `redis://redis:6379/6` |
| `LOG_LEVEL` | API/worker log level | `info` |

See `dsx_connect/config.py` for the full BaseSettings definition.

## Invoke tasks

`invoke` provides common automation. Install the deps (`pip install invoke`) then run from the repo root:

```bash
inv lint        # run pre-configured formatting / lint checks
inv tests       # execute pytest suite
inv prepare     # build dist/dsx-connect-<ver>/ with all artifacts
inv release     # bump patch version, prepare, build docker image (see tasks.py for details)
```

`inv --list` prints the complete catalog.

## Development tips

- When debugging Celery tasks, set `LOG_LEVEL=debug` and run the target worker in the foreground; logs include payload metadata and DSXA responses.
- To profile API requests, run the API with `--reload` (`uvicorn`’s autoreload) by exporting `DSXCONNECT_USE_RELOAD=true` before invoking `dsx-connect-api-start.py`.
- If you need alternate `.dev.env` variants, point the loader at a different file via `DSX_DEV_ENV_FILE=/path/to/custom.env python dsx_connect/dsx-connect-api-start.py`.

## Next steps

- Deployment guides, Helm values, and connector instructions now live under `docs/`. Start with `docs/index.md` or render them locally via `mkdocs serve`.
- The packaged distribution produced by `inv prepare` contains everything required for release (helm chart, docker-compose, start scripts).

Happy hacking!***
