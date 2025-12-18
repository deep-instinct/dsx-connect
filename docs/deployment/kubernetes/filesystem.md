# Filesystem Connector — Helm Deployment

Deploy the `filesystem-connector-chart` (under `connectors/filesystem/deploy/helm`) to scan on-prem or mounted network shares from Kubernetes.

## Prerequisites

- Kubernetes 1.19+ cluster with `kubectl`.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart`.
- A volume (PVC, hostPath, or CSI driver) that exposes the filesystem to be scanned.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

1. Provision the volume and (if using PVC) bind it in the connector namespace.
2. Decide where the volume should mount inside the pod (default `/app/scan_folder`).
3. Confirm the namespace can reach dsx-connect’s service/ingress.

## Configuration

### Required settings

- `scanVolume.*`: enable the mount and point to the PVC/hostPath plus `mountPath`.
- `env.DSXCONNECTOR_ASSET`: automatically set to `scanVolume.mountPath`, override if needed.
- `env.DSXCONNECTOR_FILTER`: optional rsync-style include/exclude list (see [Filter reference](../../reference/filters.md)).
- Monitoring flags: `env.DSXCONNECTOR_MONITOR`, `env.DSXCONNECTOR_MONITOR_FORCE_POLLING`, `env.DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS`.
- Remediation: `env.DSXCONNECTOR_ITEM_ACTION`, `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`.
- `workers` and `replicaCount` for concurrency/HA.

### Storage examples

PVC:

```yaml
scanVolume:
  enabled: true
  existingClaim: my-files-pvc
  mountPath: /app/scan_folder
```

HostPath (single-node dev):

```yaml
scanVolume:
  enabled: true
  hostPath: /Users/<you>/scan-data
  mountPath: /app/scan_folder
```

Verify after deployment:

```bash
kubectl exec -it deploy/filesystem-connector -- ls /app/scan_folder
```

### dsx-connect endpoint

Defaults to `http://dsx-connect-api` (or HTTPS when TLS is on). Override via `env.DSXCONNECTOR_DSX_CONNECT_URL` for external endpoints.

### Authentication (Optional)
See [Using DSX-Connect Authentication](../authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](../tls.md).

### Ingress & NetworkPolicy (optional)

- Enable `ingressWebhook` if you must expose `/filesystem-connector/webhook/event`.
- Use `networkPolicy.allowFrom` to restrict ingress to dsx-connect and your ingress controller (example in the chart values).

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install fs-dev oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
  --version <chart-version> \
  --set scanVolume.enabled=true \
  --set scanVolume.existingClaim=my-pvc \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/filesystem-connector -f
```

## Scaling guidance

- Increase `workers` for additional in-pod `read_file` concurrency.
- Raise `replicaCount` for HA. Each pod registers independently; replicas do not split an individual full scan but improve throughput/resiliency.

See `connectors/filesystem/deploy/helm/values.yaml` for the full parameter reference.
