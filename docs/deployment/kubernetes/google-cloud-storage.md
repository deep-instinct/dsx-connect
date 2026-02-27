# Google Cloud Storage Connector — Helm Deployment

Use this guide to deploy the `google-cloud-storage-connector-chart` for full scans, monitoring scans, and remediation actions.

## Prerequisites

- Kubernetes 1.19+ and `kubectl`.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart`.
- A Google Cloud service account JSON key with the permissions listed in [Reference → Google Cloud Credentials](../../reference/google-cloud-credentials.md).
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

Create the service-account Secret before installing:

```yaml
# gcp-sa-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: gcp-sa
type: Opaque
stringData:
  service-account.json: |
    { ...your JSON key... }
```

```bash
kubectl apply -f gcp-sa-secret.yaml
```

The chart references `gcp-sa` by default; set `serviceAccount.secretName` if you use a different name.

## Configuration

### Required settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_ASSET` | Bucket or `bucket/prefix` root to scan. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude list relative to the asset root (see [Filter reference](../../reference/filters.md)). |
| `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Remediation rules (`nothing`, `delete`, `move`, `move_tag`, `tag`). |
| `env.DSXCONNECTOR_MONITOR` | `"true"` to enable on-access scanning via Pub/Sub. |
| `workers`, `replicaCount` | Concurrency and HA knobs. |

### Monitoring inputs

When `env.DSXCONNECTOR_MONITOR=true`, populate the Pub/Sub settings:

| Key | Description |
| --- | --- |
| `env.GCS_PUBSUB_PROJECT_ID` | Project that owns the Pub/Sub subscription. |
| `env.GCS_PUBSUB_SUBSCRIPTION` | Subscription name or full path (`projects/<proj>/subscriptions/<sub>`). |
| `env.GCS_PUBSUB_ENDPOINT` | Optional override (useful for local emulators). Leave blank for production. |

Pub/Sub is the recommended trigger path. You can also drive the connector via `/webhook/event` from Cloud Functions/Run; in that case leave `env.DSXCONNECTOR_MONITOR=false` and expose the webhook ingress.

### dsx-connect endpoint

Defaults to the in-cluster service (`http://dsx-connect-api`). Override via `env.DSXCONNECTOR_DSX_CONNECT_URL` for external deployments.

### Authentication (Optional)
See [Using DSX-Connect Authentication](authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](tls.md).

### Webhook ingress (optional)

Enable `ingressWebhook` to expose `/google-cloud-storage-connector/webhook/event` if you rely on Cloud Functions/Run instead of Pub/Sub. Lock ingress down via annotations or NetworkPolicy so only trusted sources can reach it.

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install gcs-dev oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET=my-bucket/prefix \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/google-cloud-storage-connector -f
```

## Scaling

- Increase `workers` for additional in-pod concurrency.
- Raise `replicaCount` for HA or more `read_file` throughput; each pod registers separately with dsx-connect.
- For Pub/Sub, ensure your subscription acknowledgement deadlines accommodate scan duration.

Refer to `connectors/google_cloud_storage/deploy/helm/values.yaml` for the full option set.
