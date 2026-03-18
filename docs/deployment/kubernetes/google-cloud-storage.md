# Google Cloud Storage Connector — Helm Deployment

Use this guide to deploy the `google-cloud-storage-connector-chart` for full scans, monitoring, and remediation actions.

## Prerequisites

- Kubernetes 1.19+ and `kubectl`.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart`.
- A Google Cloud service account JSON key with permissions listed in [Google Cloud Credentials](../../reference/google-cloud-credentials.md).
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](index.md#kubernetes-secrets-and-credentials).

## Minimal Deployment

1. Create the GCP service-account Secret:

```yaml
# connectors/google_cloud_storage/deploy/helm/examples/gcp-sa-secret.yaml
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
kubectl apply -f connectors/google_cloud_storage/deploy/helm/examples/gcp-sa-secret.yaml
```

2. Install with minimal values:

```bash
helm install gcs-dev oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET=my-bucket/prefix \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

3. Verify:

```bash
helm list
kubectl get pods
kubectl logs deploy/google-cloud-storage-connector -f
```

For pulled-chart installs and GitOps/production patterns, see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Required Settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_ASSET` | Bucket or `bucket/prefix` root to scan. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude list relative to the asset root (see [Filter reference](../../reference/filters.md)). |
| `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Remediation rules (`nothing`, `delete`, `move`, `move_tag`, `tag`). |
| `workers`, `replicaCount` | Concurrency and HA knobs. |

### Connector-specific

| Key | Description |
| --- | --- |
| `gcp.credentialsSecretName` | Secret name containing `service-account.json` (default `gcp-sa`). |
| `env.DSXCONNECTOR_DSX_CONNECT_URL` | Override dsx-connect endpoint when not using in-cluster default (`http://dsx-connect-api`). |

## Advanced Settings

### Auth

See [Using DSX-Connect Authentication](authentication.md).

### TLS

See [Deploying with SSL/TLS](tls.md).

## Monitoring Settings

Monitoring is typically Pub/Sub-based.

Enable monitoring:

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_MONITOR` | `"true"` to enable on-access scanning via Pub/Sub. |
| `env.GCS_PUBSUB_PROJECT_ID` | Project that owns the subscription. |
| `env.GCS_PUBSUB_SUBSCRIPTION` | Subscription name or full path (`projects/<proj>/subscriptions/<sub>`). |
| `env.GCS_PUBSUB_ENDPOINT` | Optional endpoint override (for local emulators). |

Notes:

- Pub/Sub is the recommended trigger path.
- Webhook alternative is supported via `/webhook/event` if you route events from Cloud Run/Functions or middleware.
- For webhook mode, keep `env.DSXCONNECTOR_MONITOR=false` and expose `ingressWebhook`.

{% include-markdown "shared/_common_connector.md" %}
