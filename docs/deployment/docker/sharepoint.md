# SharePoint Connector — Docker Compose

This guide shows how to deploy the SharePoint connector with Docker Compose for quick testing/POV.

## Prerequisites
- Docker installed locally (or a container VM)
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Examples below assume the extracted folder is `dsx-connect-<core_version>/`. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- SharePoint app registration credentials (tenant ID, client ID, client secret). See Reference → [Azure Credentials](../../reference/azure-credentials.md) for a step-by-step walkthrough.
- A Docker network shared with dsx‑connect (example: `dsx-connect-network`)

## Compose File
In the extracted bundle, use `dsx-connect-<core_version>/sharepoint-connector-<connector_version>/docker-compose-sharepoint-connector.yaml`.

### Core connector env (common across connectors)

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_DSX_CONNECT_URL` | dsx-connect base URL (use `http://dsx-connect-api:8586` on the shared Docker network). |
| `DSXCONNECTOR_CONNECTOR_URL` | Callback URL dsx-connect uses to reach the connector (defaults to the service name inside the Docker network). |
| `DSXCONNECTOR_ASSET` | SharePoint scope, e.g., full site URL or doc library/folder path. |
| `DSXCONNECTOR_FILTER` | Optional rsync‑style include/exclude rules relative to the asset. |
| `DSXCONNECTOR_ITEM_ACTION` | What to do on malicious verdicts (`nothing`, `delete`, `move`, `move_tag`). Set to `move`/`move_tag` to relocate files after verdict. |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Destination (site/doc lib/folder path or label) for moved items when using `move`/`move_tag`. |

### SharePoint-specific settings

Define these values in your Compose environment (the sample file expects plain `SP_*` variables in the shell/`.env` file; the compose template expands them to the connector-ready `DSXCONNECTOR_SP_*` envs).

| Variable | Description |
| --- | --- |
| `SP_TENANT_ID` | Azure AD tenant ID for the SharePoint app registration. |
| `SP_CLIENT_ID` | Client ID for the SharePoint app registration. |
| `SP_CLIENT_SECRET` | Client secret for the SharePoint app registration (store securely). |
| `SP_VERIFY_TLS` | Optional override (`true`/`false`) for Graph TLS verification (defaults to `true`). |
| `SP_CA_BUNDLE` | Optional CA bundle path for Graph TLS verification. |
| `SP_WEBHOOK_ENABLED` | Set to `true` to enable Microsoft Graph change notifications (optional). |
| `SP_WEBHOOK_URL` | Public HTTPS URL Graph calls for change notifications (required when webhooks enabled). |
| `SP_WEBHOOK_CLIENT_STATE` | Optional shared secret Graph includes in webhook payloads. |
| `SP_WEBHOOK_CHANGE_TYPES` | Optional override of Graph change types (default `updated`). |

Copy the sample env file and edit it:
```bash
cp dsx-connect-<core_version>/sharepoint-connector-<connector_version>/.sample.sharepoint.env \
  dsx-connect-<core_version>/sharepoint-connector-<connector_version>/.env
```

Example `.env` values:

```bash
# SharePoint credentials
SP_TENANT_ID=xxx
SP_CLIENT_ID=xxx
SP_CLIENT_SECRET=xxx

# Optional overrides
SP_VERIFY_TLS=true
SP_CA_BUNDLE=

# Change notifications (optional)
SP_WEBHOOK_ENABLED=false
SP_WEBHOOK_URL=
SP_WEBHOOK_CLIENT_STATE=
```

Launch with:
```bash
docker compose --env-file dsx-connect-<core_version>/sharepoint-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/sharepoint-connector-<connector_version>/docker-compose-sharepoint-connector.yaml up -d
```

## Assets and Filters
- `DSXCONNECTOR_ASSET` should be set to your SharePoint scope (site/doc lib/folder). Navigate to the exact folder in SharePoint Online, grab the full URL (e.g., `https://contoso.sharepoint.com/sites/Site/Shared%20Documents/dsx-connect/scantest`), and paste it here.
- Filters are evaluated relative to that scope (children).
- See Reference → [Assets & Filters](../../reference/assets-and-filters.md) for sharding/partition guidance.

## Notes
- Use `DSXCONNECTOR_ASSET` to configure the SharePoint URL scope (site/doc lib/folder).

## TLS Options
See [Deploying with SSL/TLS](./tls.md) for Docker Compose examples (core + connectors), including runtime-mounted certs and local-dev self-signed cert generation.

## Webhook Exposure
If you expose SharePoint webhook callbacks or other HTTP endpoints outside Docker, tunnel or publish the host port mapped to `8640` (compose default when ports are enabled). Keep `DSXCONNECTOR_CONNECTOR_URL` pointing to the Docker-network URL (e.g., `http://sharepoint-connector:8640`) so dsx-connect can reach the container internally.
