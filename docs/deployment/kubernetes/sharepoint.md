# SharePoint Connector — Helm Deployment

Deploy the `sharepoint-connector-chart` (under `connectors/sharepoint/deploy/helm`) to scan SharePoint Online document libraries.

## Prerequisites

- Kubernetes 1.19+ cluster and `kubectl`.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart`.
- Microsoft Entra app credentials and Graph application permissions (see [Azure Credentials](../../reference/azure-credentials.md)).
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](index.md#kubernetes-secrets-and-credentials).

## Minimal Deployment

1. Create the SharePoint credentials Secret:

```bash
kubectl create secret generic sharepoint-credentials \
  --from-literal=DSXCONNECTOR_SP_TENANT_ID=<tenant-id> \
  --from-literal=DSXCONNECTOR_SP_CLIENT_ID=<client-id> \
  --from-literal=DSXCONNECTOR_SP_CLIENT_SECRET=<client-secret>
```

Note: this chart currently expects secret keys named `DSXCONNECTOR_SP_*` (even if your local/dev env files use `SP_*`).

(`connectors/sharepoint/deploy/helm/examples/sp-secret.yaml` provides a template if you prefer editing a manifest.)

2. Install with minimal values:

```bash
helm install sp-docs-dev oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET="https://<host>/sites/<SiteName>/Shared%20Documents" \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

3. Verify:

```bash
helm list
kubectl get pods
kubectl logs deploy/sharepoint-connector -f
```

For pulled-chart installs and GitOps/production patterns, see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Required Settings

- `env.DSXCONNECTOR_ASSET`: full SharePoint library URL (e.g., `https://contoso.sharepoint.com/sites/Site/Shared%20Documents/dsx-connect`).
- `env.DSXCONNECTOR_FILTER`: rsync-style include/exclude paths relative to the asset root (see [Filter reference](../../reference/filters.md)).
- `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`: remediation behavior.
- `workers` / `replicaCount`: concurrency and HA knobs.

### Connector-specific

- `env.DSXCONNECTOR_SP_VERIFY_TLS`: Graph TLS verification (`true`/`false`).
- `env.DSXCONNECTOR_SP_CA_BUNDLE`: optional CA bundle path for outbound Graph TLS.
- `env.DSXCONNECTOR_DSX_CONNECT_URL`: override dsx-connect endpoint when not using in-cluster default.

## Advanced Settings

### Auth

See [Using DSX-Connect Authentication](authentication.md).

### TLS

See [Deploying with SSL/TLS](tls.md).

## Monitoring Settings

SharePoint monitoring uses a **Microsoft Graph subscription callback model**:

1. Connector creates/refreshes Graph subscriptions.
2. Graph calls the connector webhook URL with change notifications.
3. Connector validates optional client state and enqueues scans.
4. Connector performs delta reconciliation to avoid missed events.

Monitoring keys:

- `env.DSXCONNECTOR_SP_WEBHOOK_ENABLED`
- `env.DSXCONNECTOR_WEBHOOK_URL` (public HTTPS callback base URL)
- `env.DSXCONNECTOR_SP_WEBHOOK_CLIENT_STATE` (optional shared secret)
- `env.DSXCONNECTOR_SP_WEBHOOK_CHANGE_TYPES`
- `env.DSXCONNECTOR_SP_WEBHOOK_EXPIRE_MINUTES`
- `env.DSXCONNECTOR_SP_WEBHOOK_REFRESH_SECONDS`

Notes:

- Webhook callback must be reachable by Microsoft Graph (not cluster-private only).
- If monitoring is disabled, full-scan/manual scan still works.
- If using `Sites.Selected`, grant site-level access to the app in addition to Graph permissions.

- Increase `workers` for additional in-pod concurrency.
- Increase `replicaCount` for HA / throughput. Each replica registers independently with dsx-connect; replicas do not shard a single full scan.

See `connectors/sharepoint/deploy/helm/values.yaml` for the full configuration surface.

{% include-markdown "shared/_common_connector.md" %}
