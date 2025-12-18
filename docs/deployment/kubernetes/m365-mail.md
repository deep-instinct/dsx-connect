# M365 Mail Connector — Helm Deployment

The Helm chart under `connectors/m365_mail/deploy/helm/` packages the connector for Kubernetes. This guide focuses on the webhook ingress and environment settings needed when Microsoft Graph must reach the connector from outside the cluster.

For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Values Overview

Key sections in `values.yaml`:

| Section | Purpose |
| --- | --- |
| `env` | Graph credentials, mailbox list, connector options, dsx-connect URL. |
| `auth_dsxconnect.enabled` | Enables DSX-HMAC verification on inbound connector routes. |
| `auth_dsxconnect.enrollmentSecretName` / `.enrollmentKey` | References the enrollment-token Secret shared with dsx-connect. |
| `webhook.publicUrl` | Optional base URL the connector advertises to Microsoft Graph (new). |
| `ingressWebhook` | Ingress definition for exposing `/m365-mail-connector/webhook/event`. |

## Retrieve Microsoft Entra credentials

> Guidance current as of 2025-11-04. The Azure portal occasionally renames blades or tabs; if you see different labels, follow the closest equivalent.

### Portal workflow

1. Sign in at [https://portal.azure.com](https://portal.azure.com) with an Application Administrator or Global Administrator account. Make sure the header shows the directory that owns the mailboxes you plan to scan. The **Tenant ID** shown under *Directory + subscription* becomes `M365_TENANT_ID`.
2. Go to *Microsoft Entra ID → App registrations → New registration*. Give the app a descriptive name (for example `dsx-m365-mail-connector`), keep the default *Single tenant* option, and click *Register*. On the Overview blade copy the **Application (client) ID** for `M365_CLIENT_ID`.
3. Open *Certificates & secrets*, add a new client secret, set the expiry that fits your rotation policy, and copy the **Value** immediately for `M365_CLIENT_SECRET` (the portal will never show it again).
4. Under *API permissions* choose *Add a permission → Microsoft Graph → Application*, add `Mail.Read`, `Mail.ReadWrite`, and `Files.Read.All`, then click *Grant admin consent* so the roles are enabled for the app.

Store the tenant ID, client ID, and secret in your secret manager of choice (Kubernetes Secret, Azure Key Vault, etc.) before you render the Helm values.

### Azure CLI alternative

1. Log the CLI into the correct tenant. Use `az login --tenant <tenant-id>` if you already know the tenant, or run `az login` first, list your available accounts with `az account list -o table`, and select the right one via `az account set --subscription "<subscription-id-or-name>"`. If you previously authenticated against another tenant, run `az logout` (or `az account clear` to remove all cached accounts) before logging in again.
2. Create the application and credentials. The snippet below mirrors the portal workflow and prints the values you need:

   ```bash
   APP_NAME="dsx-m365-mail-connector"
   GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
   az ad app create --display-name "$APP_NAME"
   CLIENT_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
   SECRET=$(az ad app credential reset --id "$CLIENT_ID" --display-name dsx-connector --years 2 --query password -o tsv)
   az ad app permission add --id "$CLIENT_ID" --api "$GRAPH_APP_ID" \
     --api-permissions Mail.Read=Role Mail.ReadWrite=Role Files.Read.All=Role
   az ad app permission admin-consent --id "$CLIENT_ID"
   TENANT_ID=$(az account show --query tenantId -o tsv)

   printf 'Tenant ID: %s\nClient ID: %s\nClient Secret: %s\n' "$TENANT_ID" "$CLIENT_ID" "$SECRET"
   ```

See [Reference → Azure Credentials](../../reference/azure-credentials.md) for expanded CLI automation (including SharePoint and OneDrive) and admin-consent troubleshooting tips.

## Basic Values Example

```yaml
env:
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8586"
  DSXCONNECTOR_CONNECTOR_URL: "http://m365-mail-connector:80"
  M365_TENANT_ID: "<tenant-guid>"
  M365_CLIENT_ID: "<app-id>"
  M365_CLIENT_SECRET: "<client-secret>"
  M365_MAILBOX_UPNS: "user1@contoso.com,user2@contoso.com"
  M365_CLIENT_STATE: "3f1e9de2-ee73-4b02-8d17-16adf0c6a28c"
  DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION: "true"

webhook:
  publicUrl: "https://mail-connector.example.com"

ingressWebhook:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
  hosts:
    - mail-connector.example.com
  tls:
    - secretName: mail-connector-tls
      hosts:
        - mail-connector.example.com
```

- `DSXCONNECTOR_CONNECTOR_URL` stays internal so dsx-connect talks to the ClusterIP service.
- `webhook.publicUrl` tells the connector which HTTPS base to register with Graph.
- The ingress exposes `/m365-mail-connector/webhook/event` publicly; terminate TLS here and reuse the same hostname in `webhook.publicUrl`.

## Chart Behaviour

- If `webhook.publicUrl` is set, the chart injects `DSXCONNECTOR_WEBHOOK_URL` for you; otherwise the connector falls back to `DSXCONNECTOR_CONNECTOR_URL`.
- The provided ingress templates only expose the webhook path. Add a second ingress or service if you want other routes reachable outside the cluster.
- Remember to create (or reuse) the enrollment-token Secret referenced under `auth_dsxconnect.enrollmentSecretName`; dsx-connect and the connector must share the same token when `auth_dsxconnect.enabled=true`.
- For near real-time scanning, you can add `DSXCONNECTOR_TRIGGER_DELTA_ON_NOTIFICATION=true` (or lower `DSXCONNECTOR_DELTA_RUN_INTERVAL_SECONDS`). The connector will still run periodic delta passes as a safety net.

## Next Steps

1. Apply the values file alongside any Secrets:
   ```bash
   helm upgrade --install m365-mail connectors/m365_mail/deploy/helm \
     -f values.yaml
   ```
2. Confirm the pod starts and the ingress hostname resolves over HTTPS.
3. Check logs for `Subscriptions reconciled` and `Delta runner` entries to ensure Graph notifications are flowing.

For more on Graph credentials and permission setup, see the Reference → [Azure Credentials](../../reference/azure-credentials.md) page.
