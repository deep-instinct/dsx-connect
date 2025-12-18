<!-- Developer documentation for the OneDrive Connector (not included in release bundles) -->
# OneDrive Connector Implementation Guide

This project implements a DSX Connector based on the DSX Connector framework. This README is a guide for how to implement, debug, and create releases of the OneDrive connector.

Deployment documentation for customers lives under `docs/deployment/kubernetes/onedrive.md` (MkDocs site).

## Development
Implement the following in `onedrive_connector.py`:
- **Startup/Shutdown:** Initialize and clean up resources (Graph client, webhook subscriptions, monitors).
- **full_scan:** Enumerate OneDrive items under the configured asset path and enqueue scan requests.
- **item_action:** Apply remediation (delete/move/tag) on files by item ID.
- **read_file:** Stream file bytes from Graph `/drives/{drive}/items/{id}/content`.
- **repo_check:** Validate connectivity and credentials.
- **webhook_event:** Handle Microsoft Graph notifications (if enabled).

## Running/Testing in an IDE/Debugger
You can run the connector via `start.py` or directly via `onedrive_connector.py`. Both paths load configuration from `config.py`, with overrides supplied by environment variables.

Typical debug launch output:
```text
INFO     dsx_logging.py      : Log level set to DEBUG
INFO     dev_env.py          : Loading dev env from connectors/onedrive/.dev.env
INFO     dsx_connector.py    : Logical connector onedrive-connector using UUID ...
INFO     start.py            : Starting OneDrive Connector on 0.0.0.0:8621
INFO     onedrive_connector.py: onedrive-connector version: 0.1.x
INFO     onedrive_connector.py: onedrive-connector configuration: ...
INFO     dsx_connector.py    : Connector is READY (registration + repo check OK).
```

### Changing Configuration (dev)
Leave `config.py` alone; override via:

- `.dev.env` next to `config.py` (ignored in releases). Sample entries:
  - `DSXCONNECTOR_USE_TLS=false`
  - `DSXCONNECTOR_TLS_CERTFILE=../../shared/deploy/certs/dev.localhost.crt`
  - `DSXCONNECTOR_TLS_KEYFILE=../../shared/deploy/certs/dev.localhost.key`
  - `DSXCONNECTOR_CONNECTOR_URL=http://localhost:8621`
  - `DSXCONNECTOR_DSX_CONNECT_URL=http://localhost:8586`
  - `DSXCONNECTOR_VERIFY_TLS=false`
  - `DSXCONNECTOR_ONEDRIVE_TENANT_ID=<tenant-guid>`
  - `DSXCONNECTOR_ONEDRIVE_CLIENT_ID=<app-client-id>`
  - `DSXCONNECTOR_ONEDRIVE_CLIENT_SECRET=<secret>`
  - `DSXCONNECTOR_ONEDRIVE_USER_ID=user@contoso.com`
  - `DSXCONNECTOR_ASSET=/Documents/dsx-connect`
  - `DSXCONNECTOR_FILTER=**/*.pdf`
  - `DSXCONNECTOR_ONEDRIVE_WEBHOOK_ENABLED=false`
- Set `DSXCONNECTOR_ENV_FILE=/path/to/custom.env` to load a different file.
- Environment variables in shells/Compose/CI (`DSXCONNECTOR_<SETTING>=...`).

## Build a Deployment Release
Use Invoke tasks under `connectors/onedrive/tasks.py`:

```bash
pip install invoke
invoke release  # builds wheel/dist + docker image under dist/ (auto-bumps patch/build number)
```

Artifacts land in `dist/`. The release task increments the patch/build automatically; edit `version.py` manually before tagging if you need a major/minor bump.

Key env vars:
- `DSXCONNECTOR_ONEDRIVE_TENANT_ID`
- `DSXCONNECTOR_ONEDRIVE_CLIENT_ID`
- `DSXCONNECTOR_ONEDRIVE_CLIENT_SECRET`
- `DSXCONNECTOR_ONEDRIVE_USER_ID`
- `DSXCONNECTOR_ASSET`
- Optional webhook vars: `DSXCONNECTOR_ONEDRIVE_WEBHOOK_ENABLED`, `DSXCONNECTOR_ONEDRIVE_WEBHOOK_URL`, `DSXCONNECTOR_ONEDRIVE_WEBHOOK_CLIENT_STATE`

## Asset & Filter Basics
- `DSXCONNECTOR_ASSET` expects a drive-relative path (copy from OneDrive UI, e.g., `/Documents/dsx-connect/scantest`).
- `DSXCONNECTOR_FILTER` uses rsync syntax (see docs/reference/filters.md). Examples:
  - `""`: scan everything under the asset root
  - `"*.pdf,*.docx"`: scan only matching extensions
  - `"reports/** -archive"`: include reports tree, skip archive folder

## Permissions (Microsoft Graph Application)
Grant the Azure AD app the least privileges required:
- Read: `Files.Read.All` or `Sites.Read.All`
- Write/remediation: `Files.ReadWrite.All` or `Sites.ReadWrite.All`
- Webhooks require `offline_access` + relevant Graph permissions so subscriptions can be created.

## Webhooks
- Enable via `DSXCONNECTOR_ONEDRIVE_WEBHOOK_ENABLED=true` and provide `WEBHOOK_URL` + `WEBHOOK_CLIENT_STATE`.
- Expose `/onedrive-connector/webhook/event` through ingress (`deploy/helm/templates/ingress-webhook.yaml` template provided).
- Graph requires the endpoint to respond to validation tokens; the connector handles this automatically once configured.

## Compose / Helm
- Docker Compose sample under `deploy/docker` (set env vars via `.env`).
- Helm chart under `deploy/helm/` with TLS/auth/ingress toggles.

## Invoke Tasks Overview
- `invoke clean` – remove build/dist artifacts.
- `invoke build` – build wheel + source dist.
- `invoke docker-build` – build connector image.
- `invoke release` – run clean → build → docker-build.

Keep the README up to date when adding new env vars, permissions, or deployment behaviors.
