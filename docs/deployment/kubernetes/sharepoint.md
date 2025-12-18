# SharePoint Connector — Helm Deployment

Deploy the `sharepoint-connector-chart` (under `connectors/sharepoint/deploy/helm`) to scan SharePoint Online document libraries.

## Prerequisites

- Kubernetes 1.19+ cluster and `kubectl`.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart`.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

Create a Secret containing the Microsoft Entra (Azure AD) app credentials:

```bash
kubectl create secret generic sharepoint-credentials \
  --from-literal=DSXCONNECTOR_SP_TENANT_ID=<tenant-id> \
  --from-literal=DSXCONNECTOR_SP_CLIENT_ID=<client-id> \
  --from-literal=DSXCONNECTOR_SP_CLIENT_SECRET=<client-secret>
```

(`connectors/sharepoint/deploy/helm/sp-secret.yaml` provides a template if you prefer editing a manifest.)

## Configuration

### Required settings

- `env.DSXCONNECTOR_ASSET`: full SharePoint library URL (e.g., `https://contoso.sharepoint.com/sites/Site/Shared%20Documents/dsx-connect`).
- `env.DSXCONNECTOR_FILTER`: rsync-style include/exclude paths relative to the asset root (see [Filter reference](../../reference/filters.md)).
- `env.DSXCONNECTOR_DISPLAY_NAME`: optional UI label.
- `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`: remediation behavior.
- `workers` / `replicaCount`: concurrency and HA knobs.

### dsx-connect endpoint

Defaults to the in-cluster dsx-connect service. Override via `env.DSXCONNECTOR_DSX_CONNECT_URL` if dsx-connect is exposed through another hostname.

### Authentication (Optional)
See [Using DSX-Connect Authentication](../authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](../tls.md).

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install sp-docs-dev oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET="https://<host>/sites/<SiteName>/Shared%20Documents" \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/sharepoint-connector -f
```

## Scaling guidance

- Increase `workers` for additional in-pod concurrency.
- Increase `replicaCount` for HA / throughput. Each replica registers independently with dsx-connect; replicas do not shard a single full scan.

See `connectors/sharepoint/deploy/helm/values.yaml` for the full configuration surface.
