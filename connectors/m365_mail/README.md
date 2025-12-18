<!-- Developer documentation for the M365 Mail Connector (not included in release bundles) -->
# M365 Mail Connector Implementation Guide

This connector ingests Microsoft 365 email events (delta queries and optional Microsoft Graph webhooks), forwards attachments to DSXA via dsx-connect, and performs remediation actions (delete/move/tag/strip attachments). Use this README while developing or releasing the connector. Customer-facing deployment steps live under `docs/deployment/docker/m365-mail.md` and `docs/deployment/kubernetes/m365-mail.md` (MkDocs).

## Development Workflow

### Core implementation
- `m365_mail_connector.py` hosts the FastAPI app and implements the DSX Connector handlers (`full_scan`, `read_file`, `item_action`, `repo_check`, `webhook_event`).
- `tasks.py` exposes Invoke tasks for building releases and Docker images.
- `deploy/` contains Compose + Helm assets for packaging.

### Running locally / via IDE
Run `start.py` or launch through your IDE. Configuration loads from `config.py`, overridden via environment variables. A typical start looks like:
```text
INFO dsx_logging.py      : Log level set to DEBUG
INFO dev_env.py          : Loading dev env from connectors/m365_mail/.dev.env
INFO dsx_connector.py    : Logical connector m365-mail-connector using UUID ...
INFO start.py            : Starting M365 Mail Connector on 0.0.0.0:8615
INFO m365_mail_connector : m365-mail-connector version: 0.5.x
INFO dsx_connector.py    : Connector is READY (registration + repo check OK)
```

### Local config overrides
Leave `config.py` unchanged and use one of the following:
- `.dev.env` alongside `config.py` (ignored in release bundles). Example entries:
  - `DSXCONNECTOR_USE_TLS=false`
  - `DSXCONNECTOR_TLS_CERTFILE=../../shared/deploy/certs/dev.localhost.crt`
  - `DSXCONNECTOR_TLS_KEYFILE=../../shared/deploy/certs/dev.localhost.key`
  - `DSXCONNECTOR_CONNECTOR_URL=http://localhost:8615`
  - `DSXCONNECTOR_DSX_CONNECT_URL=http://localhost:8586`
  - `DSXCONNECTOR_VERIFY_TLS=false`
  - `DSXCONNECTOR_M365_TENANT_ID=<tenant-guid>`
  - `DSXCONNECTOR_M365_CLIENT_ID=<app-client-id>`
  - `DSXCONNECTOR_M365_CLIENT_SECRET=<secret>`
  - `DSXCONNECTOR_M365_MAILBOX_UPNS=user1@contoso.com,user2@contoso.com`
  - `DSXCONNECTOR_ASSET=user1@contoso.com` (alias of mailbox_UPNS)
  - `DSXCONNECTOR_FILTER=**/*.pdf`
  - `DSXCONNECTOR_M365_WEBHOOK_URL=https://<public-host>/m365-mail-connector/webhook/event`
  - `DSXCONNECTOR_M365_CLIENT_STATE=<shared-secret>`
- Set `DSXCONNECTOR_ENV_FILE=/path/to/another.env` to load a different file.
- Override per-shell/Compose/CI using `DSXCONNECTOR_<SETTING>`.

## Release Builds
Use Invoke from the connector root:
```bash
pip install invoke
invoke release   # clean + build wheel + docker build (auto-bumps patch/build number)
```
Artifacts land in `dist/` (Python sdist/wheel, Docker image tar if configured). The `invoke release` task increments the build number automatically; bump major/minor versions manually in `version.py` before tagging if needed.

## Key Environment Variables
| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_M365_TENANT_ID` | Azure AD tenant hosting the app registration. |
| `DSXCONNECTOR_M365_CLIENT_ID` | Application (client) ID. |
| `DSXCONNECTOR_M365_CLIENT_SECRET` | Client secret (never commit). |
| `DSXCONNECTOR_M365_MAILBOX_UPNS` / `DSXCONNECTOR_ASSET` | Comma-separated mailbox UPNs to scan. |
| `DSXCONNECTOR_FILTER` | Optional rsync-style filters (see docs/reference/filters.md). |
| `DSXCONNECTOR_ITEM_ACTION` | `nothing`, `delete`, `move`, `move_tag`, or `tag`. |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Target folder name when moving/tagging. |
| `DSXCONNECTOR_M365_WEBHOOK_URL` | Public HTTPS endpoint for Graph notifications (defaults to connector URL). |
| `DSXCONNECTOR_M365_CLIENT_STATE` | clientState value Graph must echo (prevents spoofed notifications). |
| `DSXCONNECTOR_MAX_ATTACHMENT_BYTES` | Cap on attachment size (default 50 MB). |
| `DSXCONNECTOR_HANDLE_REFERENCE_ATTACHMENTS` | `true/false` – download cloud attachments referenced by messages. |

## Graph Permissions
Grant the Azure AD app the following Microsoft Graph application permissions (minimum):
- Read-only scans: `Mail.Read`, `Mail.ReadBasic.All`
- Remediation (move/delete): `Mail.ReadWrite`
- Webhooks: `offline_access` + `Mail.Read` (Graph requires background access)
After granting, remember to `Admin consent` the permissions or use `Sites.Selected`-style delegation if locking down scope.

## Webhooks vs Delta Queries
- **Delta polling**: Connector periodically runs `/users/{id}/messages/delta` to find new mail (controlled by `delta_run_interval_seconds`).
- **Webhooks**: When `DSXCONNECTOR_M365_WEBHOOK_URL` + `client_state` are set, the connector registers Graph subscriptions and reacts immediately to notifications. Expose `/m365-mail-connector/webhook/event` via ingress (templates under `deploy/helm`).
- You can enable both: webhooks trigger fast processing, delta provides backfill/resilience.

## Compose / Helm
- Docker Compose sample in `deploy/docker/` for local testing (set secrets via `.env`).
- Helm chart under `deploy/helm/` with values for TLS, auth, ingress, and webhook exposure.

## Invoke Task Reference
- `invoke clean` – remove build artifacts.
- `invoke build` – build Python packages.
- `invoke docker-build` – container image. 
- `invoke release` – clean + build + docker-build.

Keep this README updated whenever env vars, permissions, or deployment behavior changes.
