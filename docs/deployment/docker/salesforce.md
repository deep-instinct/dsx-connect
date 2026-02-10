# Salesforce Connector — Docker Deployment

Use this guide to run the Salesforce connector alongside dsx-connect via Docker Compose. It mirrors `connectors/salesforce/deploy/docker-compose-salesforce-connector.yaml`.

## Prerequisites

- Local Docker daemon.
- Salesforce credentials: see [Salesforce Credentials](../../reference/salesforce-credentials.md).
- A Salesforce Connected App (JWT bearer recommended for production) with:
  - Consumer key.
  - Integration user with API permissions to query `ContentVersion` and download binary content.
  - Uploaded certificate for JWT bearer flow.
- Existing dsx-connect stack (API + Redis + workers) reachable from the connector container.

## Environment Configuration

Set the following variables (either in a `.env` file or inline under `environment:` in the compose file):

| Variable | Description |
| --- | --- |
| `DSXCONNECT_ENROLLMENT_TOKEN` | Enrollment token when dsx-connect auth is enabled (skip when auth disabled). |
| `DSXCONNECTOR_SF_CLIENT_ID` | Salesforce Connected App consumer key. |
| `DSXCONNECTOR_SF_AUTH_METHOD` | `auto` (default), `jwt`, or `password` (use `jwt` for production). |
| `DSXCONNECTOR_SF_JWT_PRIVATE_KEY` / `DSXCONNECTOR_SF_JWT_PRIVATE_KEY_FILE` | JWT private key (PEM or base64) or file path for JWT bearer flow. |
| `DSXCONNECTOR_SF_USERNAME` | Integration user (required for JWT). |
| `DSXCONNECTOR_SF_PASSWORD` / `DSXCONNECTOR_SF_SECURITY_TOKEN` | Username/password flow (dev/test only). |
| `DSXCONNECTOR_SF_LOGIN_URL` | `https://login.salesforce.com` (prod) or `https://test.salesforce.com` (sandbox). |
| `DSXCONNECTOR_SF_API_VERSION` | REST API version (e.g., `v60.0`). |
| `DSXCONNECTOR_ASSET` | Optional SOQL clause appended via `AND` (e.g., `ContentDocumentId = '069xx0000001234AAA'`). |
| `DSXCONNECTOR_FILTER` | Optional comma-separated file extensions (e.g., `pdf,docx`). |
| `DSXCONNECTOR_SF_WHERE`, `DSXCONNECTOR_SF_ORDER_BY`, `DSXCONNECTOR_SF_MAX_RECORDS` | Further tune the ContentVersion query / batch size. |

Example `.env` snippet:

```env
DSXCONNECTENROLLMENT_TOKEN=abc123
DSXCONNECTOR_SF_CLIENT_ID=3MVG9...appkey
DSXCONNECTOR_SF_AUTH_METHOD=jwt
DSXCONNECTOR_SF_USERNAME=dsx@customer.com
DSXCONNECTOR_SF_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

## Compose Deployment

```bash
cd connectors/salesforce/deploy
docker compose -f docker-compose-salesforce-connector.yaml up -d
```

Key points:

- The compose file expects an existing Docker network (default `dsx-connect-network`). Update `networks.dsx-network.name` if needed.
- Expose port `8670` if dsx-connect runs outside the Docker network.
- Update `DSXCONNECTOR_DSX_CONNECT_URL` if dsx-connect is not available at `http://dsx-connect-api:8586`.

## Verification

1. Check container logs:
   ```bash
   docker logs -f salesforce_connector
   ```
2. In the dsx-connect UI, verify the Salesforce connector card shows `READY`.
3. Run a full scan from the UI or CLI and confirm `ContentVersion` items queue and stream into DSXA.

## Production Notes

- Never commit Salesforce secrets to Git. Use Docker secrets, env files stored in password managers, or inject env vars via your orchestrator.
- For TLS between dsx-connect and the connector, set `DSXCONNECTOR_USE_TLS=true` and point to cert/key files.
- When auth is enabled on dsx-connect, set `DSXCONNECT_ENROLLMENT_TOKEN` before the connector registers.
