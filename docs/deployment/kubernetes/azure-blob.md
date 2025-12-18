# Azure Blob Storage Connector — Helm Deployment

Use this guide to deploy `azure-blob-storage-connector-chart` (found under `connectors/azure_blob_storage/deploy/helm`). The same instructions apply whether you pull the chart from the repository or from the OCI registry.

## Prerequisites

- Kubernetes 1.19+ cluster and `kubectl` context.
- Helm 3.2+.
- Access to the connector chart in OCI: `oci://registry-1.docker.io/dsxconnect/azure-blob-connector-chart`.
- Optional: `openssl` for validating TLS assets.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

1. Create the Azure Storage connection-string Secret **before** installing the chart:
   - Edit and apply `connectors/azure_blob_storage/deploy/helm/azure-secret.yaml`, **or**
   - Create it inline:
     ```bash
     kubectl create secret generic azure-storage-connection-string \
       --from-literal=AZURE_STORAGE_CONNECTION_STRING='<conn-string>'
     ```
2. Confirm the namespace has network access to dsx-connect (same cluster or reachable service).

## Configuration

### Required settings

- `env.DSXCONNECTOR_ASSET`: target container (optionally `container/prefix`).
- `env.DSXCONNECTOR_FILTER`: optional rsync-style include/exclude patterns (see [Filter reference](../../reference/filters.md)).
- `env.DSXCONNECTOR_DISPLAY_NAME`: friendly label for the dsx-connect UI card.
- `env.DSXCONNECTOR_ITEM_ACTION` and `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`: control remediation behavior (`nothing`, `delete`, `tag`, `move`, `move_tag`).
- `env.DSXCONNECTOR_SCAN_CONCURRENCY`: number of parallel Azure list operations during full scans (default 10).
- `env.DSXCONNECTOR_LIST_PAGE_SIZE`: `list_blobs` page size (default 1000).
- `workers`: Uvicorn workers per pod (default 1); increase for more concurrent `read_file` traffic.
- `replicaCount`: pod count (default 1).

Filters follow rsync semantics (`?`, `*`, `**`, `+`, `-`). See the chart values file for complex examples.

### dsx-connect endpoint

The chart defaults to `http://dsx-connect-api` (or `https://dsx-connect-api` when TLS is enabled). Override with `env.DSXCONNECTOR_DSX_CONNECT_URL` if your dsx-connect instance is reachable via another hostname or port.

### Authentication (Optional)
See [Using DSX-Connect Authentication](../authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](../tls.md).

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install abs-dev oci://registry-1.docker.io/dsxconnect/azure-blob-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET=my-container \
  --set-string env.DSXCONNECTOR_FILTER="**/*.docx" \
  --set-string image.tag=<connector-version>
```

If you omit `image.tag`, Helm uses the chart’s `appVersion`. Pinning it is recommended for reproducibility.

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/azure-blob-storage-connector -f
```

## Scaling & tuning

- Increase `workers` and/or `replicaCount` for more concurrent `read_file` responses or HA.
- Adjust `DSXCONNECTOR_SCAN_CONCURRENCY` / `DSXCONNECTOR_LIST_PAGE_SIZE` if Azure throttles (reduce) or if you need faster enumeration (increase carefully).
- Each pod registers independently with dsx-connect; replicas do not parallelize a single full scan but do improve availability.

See `connectors/azure_blob_storage/deploy/helm/values.yaml` for the complete parameter catalog.
