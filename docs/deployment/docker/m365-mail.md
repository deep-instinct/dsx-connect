# M365 Email Connector — Docker Compose

This guide explains how to run the `m365-mail-connector` (Outlook / Exchange Online) with Docker Compose for demos and local development.

## Prerequisites
- Docker installed and a network shared with the dsx-connect stack (for example, `dsx-connect-network`).
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Examples below assume the extracted folder is `dsx-connect-<core_version>/`. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- dsx-connect API running (Docker Compose or K8S); note the base URL exposed to the connector.
- Microsoft Graph application (client credentials flow) with the required permissions (see Reference → [Azure Credentials](../../reference/azure-credentials.md) for detailed steps):
  - `Mail.Read` (or `Mail.ReadWrite` if remediation actions are enabled)
  - `Files.Read.All` if you plan to download `referenceAttachment`s (optional for v1)
- Service principal credentials: supply via `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET`.
- List of mailbox UPNs or mailbox folders to monitor via `M365_MAILBOX_UPNS` (comma-separated).
- Public HTTPS endpoint for Graph change notifications (e.g., port-forward via ngrok/Cloudflare Tunnel). Only `/{connector}/webhook/event` must be reachable from Microsoft Graph.

## Compose File
In the extracted bundle, start from `dsx-connect-<core_version>/m365-mail-connector-<connector_version>/docker-compose-m365-mail-connector.yaml`. It references the published connector image and binds port `8650` (container + host) so you can forward webhooks easily.

### Core connector env (common across connectors)

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_DSX_CONNECT_URL` | Base URL for dsx-connect (e.g., `http://dsx-connect-api:8586` on the shared Docker network). |
| `DSXCONNECTOR_CONNECTOR_URL` | Internal callback URL dsx-connect uses to reach this connector (defaults to the service name inside the Docker network, e.g., `http://m365-mail-connector:8650`). |
| `DSXCONNECTOR_ASSET` | Alias for `M365_MAILBOX_UPNS`; comma-separated mailbox or mailbox/folder entries (e.g., `user@contoso.com/Inbox`). |
| `DSXCONNECTOR_FILTER` | Optional rsync-style filters for attachment names under the asset (see Reference → [Filters](../../reference/filters.md)). |
| `DSXCONNECTOR_ITEM_ACTION` | What dsx-connect should do on malicious verdicts (`nothing`, `delete`, `move`, `move_tag`). Set to `move`/`move_tag` when you want the connector to remediate mail. |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Optional string that accompanies move/tag actions (defaults to `dsxconnect-quarantine`; keep unless you have connector-specific logic). |

### M365-specific settings

| Variable | Description |
| --- | --- |
| `M365_MAILBOX_UPNS` | Comma-separated list of mailbox UPNs (e.g., `user@contoso.com,groupscan@contoso.com`). |
| `M365_TENANT_ID`, `M365_CLIENT_ID`, `M365_CLIENT_SECRET` | Microsoft Graph app registration credentials. |
| `M365_CLIENT_STATE` | Optional shared secret for webhook `clientState` validation. |
| `DSXCONNECTOR_WEBHOOK_URL` | Optional public HTTPS base URL for Graph webhooks (falls back to `DSXCONNECTOR_CONNECTOR_URL`). Use this with ngrok or another tunnel so dsx-connect can stay on the internal URL while Graph reaches the connector. |
| `DSXCONNECTOR_DELTA_RUN_INTERVAL_SECONDS` | Background delta backfill cadence (defaults to 600). |
| `DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION` | When `true`, run a delta pass immediately after each webhook (default `false`). |

Example:

```bash
cp dsx-connect-<core_version>/m365-mail-connector-<connector_version>/.sample.m365-mail.env \
  dsx-connect-<core_version>/m365-mail-connector-<connector_version>/.env
# edit dsx-connect-<core_version>/m365-mail-connector-<connector_version>/.env (tenant/client creds, mailbox scope, optional webhook URL)
docker compose --env-file dsx-connect-<core_version>/m365-mail-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/m365-mail-connector-<connector_version>/docker-compose-m365-mail-connector.yaml up -d
```

## Assets, Filters, and Sharding
- `DSXCONNECTOR_ASSET` maps directly to the mailbox scope:
  - Entire mailbox: `user@contoso.com`
  - Specific folder: `user@contoso.com/Finance`
- Use multiple connector instances when sharding large estates (per mailbox or per folder). Each instance should receive a distinct asset and mailbox list.
- Apply `DSXCONNECTOR_FILTER` when you want to include/exclude attachment names (e.g., `**/*.zip`, `-tmp/`). Filters are evaluated relative to the asset’s mailbox/folder path.

See Reference → [Assets & Filters](../../reference/assets-and-filters.md) for sharding patterns.

## Webhook Exposure
Microsoft Graph must reach `https://<public-host>/m365-mail-connector/webhook/event`.

1. Expose the container’s port `8650` via an HTTPS tunnel or reverse proxy (ngrok, Cloudflare Tunnel, etc.). The tunnel terminates on the Docker host and forwards traffic to `localhost:8650`.
2. Register Microsoft Graph subscriptions using that public HTTPS URL.
3. Leave `DSXCONNECTOR_CONNECTOR_URL` pointing at the Docker-network hostname (e.g., `http://m365-mail-connector:8650`) so dsx-connect can reach the connector internally.

## Compose vs. Kubernetes
- **Docker Compose**
  - `DSXCONNECT_AUTH__ENABLED` remains `false`; dsx-connect does not require enrollment tokens or DSX-HMAC inbound signatures.
  - The connector stores Graph credentials only in memory; no Kubernetes Secret orchestration is needed.
  - Delta tokens are persisted through dsx-connect’s KV API, but the calls are unsigned in local dev.
- **Kubernetes**
  - Enable dsx-connect enrollment + HMAC so every connector POST/GET is signed.
  - Mount enrollment tokens through Secrets (`DSXCONNECT_ENROLLMENT_TOKEN`) and set `auth_dsxconnect.enabled=true` (plus `auth_dsxconnect.enrollmentSecretName`) in both charts.
  - Ingress/NetworkPolicy defaults expose only `/webhook_event` publicly and restrict other paths to dsx-connect.

Use Compose for local validation and switch to the Helm charts (`connectors/m365_mail/deploy/helm/`) for production-grade deployments with enrollment and DSX-HMAC enforced.

## Azure Credentials Reference

See Reference → [Azure Credentials](../../reference/azure-credentials.md) for a portal walkthrough, CLI automation, and Graph API fallback commands for registering the application, capturing tenant/client IDs, generating client secrets, and granting Microsoft Graph application permissions.

### Exposing the Webhook Locally (ngrok example)

Microsoft Graph delivers notifications only to publicly reachable HTTPS endpoints. For local testing:

1. Install ngrok and run `ngrok http 8650`. ngrok prints both HTTP and HTTPS URLs (e.g., `https://<random>.ngrok-free.app`).
2. Keep `DSXCONNECTOR_CONNECTOR_URL=http://127.0.0.1:8650` so dsx-connect calls the connector over localhost.
3. Set `DSXCONNECTOR_WEBHOOK_URL=https://<random>.ngrok-free.app` so the connector registers the ngrok address with Graph.
4. Restart the connector. Subscription reconciliation will now succeed, and Graph notifications will arrive at the tunneled endpoint.

Any secure tunnel (Cloudflare Tunnel, Azure Relay, etc.) works similarly: expose port 8650, note the HTTPS URL, and place it in `DSXCONNECTOR_WEBHOOK_URL`.

### Faster Scanning After Notifications

- The connector relies on Graph delta queries for durability. By default it waits `DSXCONNECTOR_DELTA_RUN_INTERVAL_SECONDS` (600s) between runs. During that interval you may see multiple webhook events, but attachments are processed when the next delta pass runs.
- To reduce latency, either lower the interval (e.g., `DSXCONNECTOR_DELTA_RUN_INTERVAL_SECONDS=30`) or set `DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION=true` so the connector runs a delta pass immediately after each webhook.
- Even with the trigger enabled, the periodic delta loop stays active to recover from missed notifications.

## Operational Notes
- The background delta runner and `@connector.full_scan` reuse the same Graph delta code path. Trigger a manual pass with `POST /dsx-connect/api/v1/connectors/full_scan/{uuid}` (optional `?limit=N`).
- Delta tokens live under the `m365/delta:<upn>` namespace in dsx-connect’s KV store. For Compose, the connector automatically initializes them when the API is reachable.
- Webhooks deliver near real-time attachment notifications; delta backfill handles drift and initial load. Keep the docker container running so subscription renewals (30-minute reconciliation loop) continue.
- Remediation actions kick in as soon as `DSXCONNECTOR_ITEM_ACTION` is set to `delete`, `move`, or `move_tag`; no extra toggle is required (the legacy `DSXCONNECTOR_ENABLE_ACTIONS` variable is ignored unless explicitly set to `false` for compatibility).

## TLS Options
See [Deploying with SSL/TLS](./tls.md) for Docker Compose examples (core + connectors), including runtime-mounted certs and local-dev self-signed cert generation.

Example override file (bundle root):
```yaml
# dsx-connect-<core_version>/m365-mail-connector-<connector_version>/docker-compose.tls.override.yaml
services:
  m365_mail_connector:
    volumes:
      - ../certs:/app/certs:ro
```

Then run with both compose files:
```bash
docker compose --env-file dsx-connect-<core_version>/m365-mail-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/m365-mail-connector-<connector_version>/docker-compose-m365-mail-connector.yaml \
  -f dsx-connect-<core_version>/m365-mail-connector-<connector_version>/docker-compose.tls.override.yaml up -d
```
