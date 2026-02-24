# DSX-Connect Monorepo

This repository houses the full DSX-Connect stack: the core orchestration service, pluggable connectors, a Python SDK for DSXA, a shared utilities module, deployment docs, and supporting tooling. Everything lives side by side so changes across components can be developed and tested together.

## Architecture at a Glance

- **dsx-connect (core)** – FastAPI-based control plane that brokers scan requests between enterprise data sources and the Deep Instinct Scanner (DSXA). It exposes the UI/API, stores connector registry state in Redis, dispatches long-running jobs through Celery workers, and enforces connector authentication (enrollment tokens + DSX-HMAC).
- **Connectors** – Service-specific adapters (AWS S3, Azure Blob, SharePoint, FileSystem, etc.) that register with dsx-connect, enumerate their assets, forward files to DSXA, and act on verdicts. Each connector is a FastAPI app built on the shared connector framework.
- **DSXA SDK** – `dsxa_sdk` provides a typed Python client (sync + async) and CLI for submitting binaries/paths/hashes to DSXA. dsx-connect workers and connectors share the same client library for DSXA calls.
- **Shared utilities** – Common helpers (logging, dev env loader, auth shared code, schemas) live under `shared/` so both dsx-connect and connectors can import them without duplicating logic.
- **Docs** – `docs/` contains the MkDocs site with deployment guides, connector references, and operational runbooks.
- **Cookiecutter** – `cookiecutter-dsx-connectors/` scaffolds new connectors (code, Helm chart, tasks, README) with the repo’s default conventions.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `dsx_connect/` | Core API, Celery workers, Helm chart, and web UI assets. |
| `connectors/` | Each connector lives in its own subdirectory with code, tests, Helm/Docker artifacts, and a README specific to that connector. |
| `dsxa_sdk/` | Python package + CLI for DSXA integrations (`README.md` and tests inside). |
| `shared/` | Cross-cutting modules (e.g., `shared/dev_env.py`, models). |
| `cookiecutter-dsx-connectors/` | Template used by `cookiecutter` to bootstrap new connectors. |
| `docs/` | MkDocs content (deployment guides, references, diagrams). |
| `tests/` | Cross-project tests (integration/contract style) that don’t belong to a single component. |

See each directory’s README for component-specific details (e.g., `dsx_connect/README.md`, `connectors/<name>/README.md`, `dsxa_sdk/README.md`).

## Getting Started

1. **Read developer tasks** – `DEVELOPER_TASKS.md` captures open work items, coding conventions, and review expectations. Start there when onboarding or picking up a ticket.
2. **Component READMEs** – Each connector and `dsx_connect` have their own README covering local dev, env vars, and release steps. Consult these before editing or running those services.
3. **Shared tooling** – Invoke tasks (`tasks.py`), Make targets, and scripts under `scripts/` assist with linting, packaging, and local orchestration.


## Online Docs 

DSX-Connect docs are hosted on GitHub Pages at: https://deep-instinct.github.io/dsx-connect/

When source docs (./docs/* or mkdocs.yml) are committed to GitHub repository, the docs are automatically rebuilt and published via GitHub Actions.

## Docs: Preview MkDocs Locally

1. Ensure the repo’s Python env is active (e.g., `python -m venv .venv && source .venv/bin/activate`).
2. Install doc tooling if not already available: `pip install -r docs/requirements.txt` (or `pip install mkdocs mkdocs-material`).
3. From the repo root run:
   ```bash
   mkdocs serve
   ```
4. Visit `http://127.0.0.1:8000` to browse the deployment guides, reference material, and connector docs. Changes to files under `docs/` hot-reload automatically.

For CI-quality builds use `mkdocs build` (outputs to `site/`). Keep docs up to date when adding new features so deployment teams have the latest instructions.
