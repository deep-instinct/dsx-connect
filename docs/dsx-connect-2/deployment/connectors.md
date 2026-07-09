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

### Deploy GCS Without Helper Scripts

Use the released OCI chart when the cluster can pull released images from Docker Hub:

```bash
export NAMESPACE=dsx-connect
export GCS_RELEASE=gcs
export GCS_VERSION=2.0.2

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic gcp-sa \
  -n "$NAMESPACE" \
  --from-file=service-account.json=/path/to/gcp-sa.json \
  --dry-run=client -o yaml | kubectl apply -f -

cp docs/dsx-connect-2/deployment/examples/gcs-connector-values.yaml \
  /tmp/gcs-connector-values.yaml
```

Full example:

```yaml
env:
  LOG_LEVEL: "debug"
  DSXCONNECTOR_APP_ENV: "dev"
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "gcs-local-1"
  DSXCONNECTOR_NG_PLATFORM: "gcs"
  DSXCONNECTOR_NG_PLATFORM_KEY: "demo-project"
  DSXCONNECTOR_ASSET: "lg-test-01"
  DSXCONNECTOR_FILTER: ""
  DSXCONNECTOR_ITEM_ACTION: "nothing"
  DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "dsxconnect-quarantine"
  DSXCONNECTOR_DATA_DIR: "/app/data"
  DSXCONNECTOR_MONITOR: "false"
  GCS_PUBSUB_PROJECT_ID: ""
  GCS_PUBSUB_SUBSCRIPTION: ""

auth_dsxconnect:
  enabled: false
  enrollmentSecretName: "dsx-dsx-connect-api-auth-enrollment"
  enrollmentKey: ENROLLMENT_TOKEN

gcp:
  credentialsSecretName: "gcp-sa"
  mountPath: "/app/creds"
  filename: "service-account.json"

dataVolume:
  enabled: true
  mountPath: "/app/data"
```

Install the released chart:

```bash
helm upgrade --install "$GCS_RELEASE" \
  oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector \
  --version "$GCS_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/gcs-connector-values.yaml
```

For monitoring deployments, start from:

```bash
cp docs/dsx-connect-2/deployment/examples/gcs-connector-monitoring-values.yaml \
  /tmp/gcs-connector-values.yaml
```

Use the local chart directory when testing an image already loaded into local k3s or Colima:

```bash
docker buildx build \
  --load \
  --tag local/dsx-connect/google-cloud-storage-connector:dev \
  -f connectors/google_cloud_storage/Dockerfile \
  .

helm upgrade --install "$GCS_RELEASE" \
  ./connectors/google_cloud_storage/deploy/helm \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/gcs-connector-values.yaml \
  --set image.repository=local/dsx-connect/google-cloud-storage-connector \
  --set image.tag=dev \
  --set image.pullPolicy=IfNotPresent
```

### Configure GCS Pub/Sub Monitoring

GCS monitoring uses a Pub/Sub topic and subscription.
Cloud Storage publishes object events to the topic, and the GCS connector consumes messages from the subscription.

Set the working variables:

```bash
export PROJECT_ID="se-project-388112"
export BUCKET="lg-test-01"
export TOPIC="gcs-object-events"
export SUBSCRIPTION="gcs-events-dsx-connector"
export CONNECTOR_SA_EMAIL="dsx-gcs-connector@${PROJECT_ID}.iam.gserviceaccount.com"
```

Enable the required APIs:

```bash
gcloud services enable storage.googleapis.com pubsub.googleapis.com \
  --project "$PROJECT_ID"
```

Create the Pub/Sub topic and subscription:

```bash
gcloud pubsub topics create "$TOPIC" \
  --project "$PROJECT_ID"

gcloud pubsub subscriptions create "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --topic "$TOPIC" \
  --ack-deadline 60
```

Allow the Cloud Storage service agent to publish bucket notifications to the topic:

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export GCS_SERVICE_AGENT="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"

gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${GCS_SERVICE_AGENT}" \
  --role "roles/pubsub.publisher"
```

Create the bucket notification:

```bash
gcloud storage buckets notifications create "gs://${BUCKET}" \
  --topic "$TOPIC" \
  --payload-format json
```

If your installed `gcloud` does not support `storage buckets notifications create`, use `gsutil`:

```bash
gsutil notification create \
  -t "$TOPIC" \
  -f json \
  "gs://${BUCKET}"
```

Grant the connector service account permission to read the bucket and consume the subscription:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/storage.objectViewer"

gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/pubsub.subscriber"
```

If the connector performs quarantine or delete remediation, grant a write-capable bucket role instead of read-only access:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/storage.objectAdmin"
```

Verify the notification and subscription:

```bash
gcloud storage buckets notifications list "gs://${BUCKET}"

gcloud pubsub subscriptions describe "$SUBSCRIPTION" \
  --project "$PROJECT_ID"
```

Enable monitoring in the GCS connector values:

```yaml
env:
  DSXCONNECTOR_MONITOR: "true"
  GCS_PUBSUB_PROJECT_ID: "se-project-388112"
  GCS_PUBSUB_SUBSCRIPTION: "gcs-events-dsx-connector"
```

The connector consumes Pub/Sub directly with the Google client SDK.
It does not need a public webhook URL for native Pub/Sub monitoring.

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

### Deploy Filesystem Without Helper Scripts

Use the released OCI chart when the cluster can pull released images from Docker Hub:

```bash
export NAMESPACE=dsx-connect
export FS_RELEASE=fs
export FILESYSTEM_VERSION=2.0.2
export HOST_SCAN_PATH=/var/dsx-connect-2-test

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

cp docs/dsx-connect-2/deployment/examples/filesystem-connector-values.yaml \
  /tmp/filesystem-connector-values.yaml
```

Edit `/tmp/filesystem-connector-values.yaml` and set `scanVolume.hostPath` to the path on the Kubernetes node.

Full example:

```yaml
env:
  LOG_LEVEL: "debug"
  DSXCONNECTOR_APP_ENV: "dev"
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "filesystem-local-1"
  DSXCONNECTOR_NG_PLATFORM: "filesystem"
  DSXCONNECTOR_NG_PLATFORM_KEY: "local-kubernetes"
  DSXCONNECTOR_ASSET: "/app/scan_folder"
  DSXCONNECTOR_FILTER: ""
  DSXCONNECTOR_ITEM_ACTION: "nothing"
  DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "/app/quarantine"
  DSXCONNECTOR_DATA_DIR: "/app/data"
  DSXCONNECTOR_MONITOR: "false"
  DSXCONNECTOR_MONITOR_FORCE_POLLING: "false"
  DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS: "1000"
  DSXCONNECTOR_SCAN_BY_PATH: "False"

auth_dsxconnect:
  enabled: false
  enrollmentSecretName: "dsx-dsx-connect-api-auth-enrollment"
  enrollmentKey: ENROLLMENT_TOKEN

scanVolume:
  enabled: true
  mountPath: "/app/scan_folder"
  hostPath: "/var/dsx-connect-2-test"

dataVolume:
  enabled: true
  mountPath: "/app/data"
```

Install the released chart:

```bash
helm upgrade --install "$FS_RELEASE" \
  oci://registry-1.docker.io/dsxconnect/filesystem-connector \
  --version "$FILESYSTEM_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/filesystem-connector-values.yaml
```

Use the local chart directory when testing a locally built image:

```bash
docker buildx build \
  --load \
  --tag local/dsx-connect/filesystem-connector:dev \
  -f connectors/filesystem/Dockerfile \
  .

helm upgrade --install "$FS_RELEASE" \
  ./connectors/filesystem/deploy/helm \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/filesystem-connector-values.yaml \
  --set image.repository=local/dsx-connect/filesystem-connector \
  --set image.tag=dev \
  --set image.pullPolicy=IfNotPresent
```

The `hostPath` must exist on the Kubernetes node where the pod runs.
For Colima, create it inside the Colima VM or start Colima with the host path mounted.

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
