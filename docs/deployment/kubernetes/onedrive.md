# OneDrive Connector — Helm Deployment

Deploy the `onedrive-connector-chart` (under `connectors/onedrive/deploy/helm`) to scan OneDrive content via delegated app credentials.

## Prerequisites

- Kubernetes 1.19+, Helm 3.2+, and `kubectl`.
- Access to `oci://registry-1.docker.io/dsxconnect/onedrive-connector-chart`.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

Create the OneDrive/Graph credentials Secret (template: `connectors/onedrive/deploy/helm/od-secret.yaml`):

```bash
kubectl create secret generic onedrive-credentials \
  --from-literal=DSXCONNECTOR_ONEDRIVE_TENANT_ID=<tenant> \
  --from-literal=DSXCONNECTOR_ONEDRIVE_CLIENT_ID=<client-id> \
  --from-literal=DSXCONNECTOR_ONEDRIVE_CLIENT_SECRET=<client-secret>
```

Ensure dsx-connect is reachable (same cluster or routable ingress). If you plan to receive Microsoft Graph webhooks, make sure `/onedrive-connector/webhook/event` can be exposed through an ingress and reachable by Graph.

## Configuration

### Required settings

- `env.DSXCONNECTOR_ONEDRIVE_TENANT_ID`, `env.DSXCONNECTOR_ONEDRIVE_CLIENT_ID`, `env.DSXCONNECTOR_ONEDRIVE_CLIENT_SECRET`: provided via the Secret above or direct env overrides.
- `env.DSXCONNECTOR_ONEDRIVE_USER_ID`: the user/drive to scan.
- `env.DSXCONNECTOR_ASSET`: drive-relative path (e.g., `/Documents/dsx-connect`).
- `env.DSXCONNECTOR_FILTER`: optional rsync-style include/exclude list (see [Filter reference](../../reference/filters.md)).
- `env.DSXCONNECTOR_ONEDRIVE_WEBHOOK_ENABLED`, `env.DSXCONNECTOR_ONEDRIVE_WEBHOOK_URL`, `env.DSXCONNECTOR_ONEDRIVE_WEBHOOK_CLIENT_STATE`: set when using Graph webhooks.
- `workers` / `replicaCount`: concurrency and HA knobs.

### dsx-connect endpoint

Defaults to the in-cluster service; override with `env.DSXCONNECTOR_DSX_CONNECT_URL` if dsx-connect is exposed elsewhere.

### Authentication (Optional)
See [Using DSX-Connect Authentication](../authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](../tls.md).

### Webhook ingress

Enable `ingressWebhook` to expose `/onedrive-connector/webhook/event` when using Graph webhooks. Restrict ingress to Microsoft Graph IPs or your ingress controller as needed.

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install onedrive-dev oci://registry-1.docker.io/dsxconnect/onedrive-connector-chart \
  --version <chart-version> \
  --set-string env.DSXCONNECTOR_ONEDRIVE_USER_ID="user@contoso.com" \
  --set-string env.DSXCONNECTOR_ASSET="/Documents/dsx-connect" \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/onedrive-connector -f
```

## Assets & filters

- `DSXCONNECTOR_ONEDRIVE_ASSET` points to the drive-relative folder. Navigate to the desired folder in OneDrive, copy the path, and paste it (for example `/Documents/dsx-connect/scantest`).
- Filters are relative to that asset path and follow rsync syntax (`?`, `*`, `**`, `+`, `-`).

See `connectors/onedrive/deploy/helm/values.yaml` for the exhaustive option set.
