# Deploy Connectors for DSX-Connect 2

Connectors register with DSX-Connect 2 and advertise the repository capabilities they support.
The control plane uses those registrations to show repository connectors, discover assets, apply protection profiles, and dispatch scans.

This page covers local Kubernetes deployment of the GCS and filesystem connectors.

## Control Plane Requirements

Deploy the DSX-Connect 2 full stack before deploying connectors:

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local-stack.yaml
```

Connectors should point at the in-cluster API service:

```text
http://dsx-connect-api:8091
```

## Build Connector Images

Build and load images for local k3s or Colima:

```bash
scripts/connectors/build-image.sh google_cloud_storage \
  --tag dev \
  --registry local/dsx-connect \
  --load

scripts/connectors/build-image.sh filesystem \
  --tag dev \
  --registry local/dsx-connect \
  --load
```

For a remote cluster, push images to a registry the cluster can pull from and use that registry during deployment.

## DSX-Connect 2 Registration Settings

Connector values for DSX-Connect 2 should include:

```yaml
env:
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "connector-instance-1"
  DSXCONNECTOR_NG_PLATFORM: "gcs"
  DSXCONNECTOR_NG_PLATFORM_KEY: "demo-project"
```

Use a stable `DSXCONNECTOR_INSTANCE_ID` for a running connector instance.
Use `DSXCONNECTOR_NG_PLATFORM_KEY` to identify the account, project, tenant, host, or other platform boundary represented by the connector.

## Deploy Google Cloud Storage

The GCS connector needs a Kubernetes Secret containing the service account JSON.
The local values expect a secret named `gcp-sa` with a key named `service-account.json`.

Example:

```bash
kubectl create secret generic gcp-sa \
  -n dsx-connect \
  --from-file=service-account.json=/path/to/gcp-sa.json
```

Deploy the connector:

```bash
scripts/connectors/deploy-k3s.sh google_cloud_storage \
  --tag dev \
  --registry local/dsx-connect \
  --release gcs \
  --namespace dsx-connect \
  -f connectors/google_cloud_storage/deploy/helm/values-local-ng.yaml \
  --pull-policy IfNotPresent
```

The local GCS values configure:

```yaml
DSXCONNECTOR_NG_PLATFORM: gcs
DSXCONNECTOR_NG_PLATFORM_KEY: demo-project
DSXCONNECTOR_ASSET: lg-test-01
DSXCONNECTOR_MONITOR: "false"
```

Use `DSXCONNECTOR_ASSET` for the default or configured bucket when running in a single-bucket mode.
As the connector evolves toward broader discovery, the platform key should represent the project or tenant boundary.

## Deploy Filesystem

Deploy the filesystem connector:

```bash
scripts/connectors/deploy-k3s.sh filesystem \
  --tag dev \
  --registry local/dsx-connect \
  --release fs \
  --namespace dsx-connect \
  -f connectors/filesystem/deploy/helm/values-local-ng.yaml \
  --pull-policy IfNotPresent
```

The local filesystem values configure:

```yaml
DSXCONNECTOR_NG_PLATFORM: filesystem
DSXCONNECTOR_NG_PLATFORM_KEY: local-colima
DSXCONNECTOR_ASSET: /app/scan_folder
DSXCONNECTOR_MONITOR: "false"
```

For real deployments, mount the host path, persistent volume, or network filesystem path that should be scanned.

## Verify Registration

Check pods:

```bash
kubectl get pods -n dsx-connect
```

Check connector logs:

```bash
kubectl logs -n dsx-connect deploy/gcs-google-cloud-storage-connector
kubectl logs -n dsx-connect deploy/fs-filesystem-connector
```

Open the Operator Console:

```text
http://127.0.0.1:8091/api/v1/ui/
```

The connectors should appear under **Assets > Connectors**.
When a connector stops heartbeating, the console should show it as offline after its lease expires.

## Tear Down Connectors

```bash
helm uninstall gcs -n dsx-connect
helm uninstall fs -n dsx-connect
```

## Common Issues

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Connector pod is `ImagePullBackOff` | Cluster cannot pull the image | Verify registry, tag, pull secret, and `image.pullPolicy` |
| GCS pod has `FailedMount` | Secret name or namespace is wrong | `kubectl get secret gcp-sa -n dsx-connect` |
| Connector starts but does not register | Control plane URL is wrong or API is unavailable | Check `DSXCONNECTOR_DSX_CONNECT_NG_URL` and API service |
| Connector registers but asset reads fail | Repository credentials or asset settings are wrong | Check connector logs and repository-specific secret values |
| Connector appears offline | Heartbeats stopped or lease expired | Check connector pod status and logs |
