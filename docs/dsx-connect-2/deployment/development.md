# DSX-Connect 2 Development Deployment

This page collects local build and helper-script workflows for DSX-Connect 2.
Use it when developing the chart, testing local images, or running on local k3s or Colima.

For release-based Kubernetes deployment, use [Deploying DSX-Connect 2 with Helm](kubernetes.md).

## Build a Local Image

Using the helper script:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag dev \
  --registry local/dsx-connect \
  --load
```

Equivalent Docker command:

```bash
docker buildx build \
  --load \
  --tag local/dsx-connect/dsx-connect:dev \
  -f dsx_connect_ng/Dockerfile \
  .
```

Use `--push` instead of `--load` when deploying to a remote cluster that pulls from a registry.

## Build Local Connector Images

Build and load connector images for local k3s or Colima:

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

Equivalent Docker commands:

```bash
docker buildx build \
  --load \
  --tag local/dsx-connect/google-cloud-storage-connector:dev \
  -f connectors/google_cloud_storage/Dockerfile \
  .

docker buildx build \
  --load \
  --tag local/dsx-connect/filesystem-connector:dev \
  -f connectors/filesystem/Dockerfile \
  .
```

For a remote cluster, push images to a registry the cluster can pull from and use that registry in the connector values.

## Deploy API-Only Mode

API-only mode is useful for a quick Operator Console and API smoke test.
It uses in-memory backends and does not run PostgreSQL, RabbitMQ, or workers.

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local.yaml
```

Use this only for API pod, service, image, and UI shell validation.
Do not use API-only mode for connector registration or scan workflow validation.

## Deploy Full-Stack Local Mode

Full-stack local mode enables PostgreSQL, RabbitMQ, and all workers.
Use this for connector registration, asset inventory, protection workflows, scan dispatch, and result processing.

Using the helper script:

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local-stack.yaml
```

Equivalent Helm command using the local chart directory:

```bash
export RELEASE=dsx-connect
export NAMESPACE=dsx-connect

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

cp docs/dsx-connect-2/deployment/examples/dsx-connect-local-image-values.yaml \
  /tmp/dsx-connect-local-values.yaml

helm upgrade --install "$RELEASE" \
  ./dsx_connect_ng/deploy/helm \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/dsx-connect-local-values.yaml
```

The local image values file points at:

```yaml
image:
  repository: local/dsx-connect/dsx-connect
  pullPolicy: IfNotPresent
  tag: dev
```

## Deploy Local Connector Images

After the DSX-Connect 2 full-stack local mode is running, deploy locally built connector images with the helper scripts.

### Google Cloud Storage

Create the GCP service-account Secret:

```bash
kubectl create secret generic gcp-sa \
  -n dsx-connect \
  --from-file=service-account.json=/path/to/gcp-sa.json
```

Deploy the local image:

```bash
scripts/connectors/deploy-k3s.sh google_cloud_storage \
  --tag dev \
  --registry local/dsx-connect \
  --release gcs \
  --namespace dsx-connect \
  -f connectors/google_cloud_storage/deploy/helm/values-local-ng.yaml \
  --pull-policy IfNotPresent
```

Equivalent Helm command using the local chart directory:

```bash
export NAMESPACE=dsx-connect
export GCS_RELEASE=gcs

cp docs/dsx-connect-2/deployment/examples/gcs-connector-values.yaml \
  /tmp/gcs-connector-values.yaml

# Edit /tmp/gcs-connector-values.yaml for your Pub/Sub project and subscription.
# For scan-only local testing before Pub/Sub is configured, set
# env.DSXCONNECTOR_MONITOR: "false".

helm upgrade --install "$GCS_RELEASE" \
  ./connectors/google_cloud_storage/deploy/helm \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/gcs-connector-values.yaml \
  --set image.repository=local/dsx-connect/google-cloud-storage-connector \
  --set image.tag=dev \
  --set image.pullPolicy=IfNotPresent
```

### Filesystem

Deploy the local image:

```bash
scripts/connectors/deploy-k3s.sh filesystem \
  --tag dev \
  --registry local/dsx-connect \
  --release filesystem \
  --namespace dsx-connect \
  -f connectors/filesystem/deploy/helm/values-local-ng.yaml \
  --pull-policy IfNotPresent
```

Equivalent Helm command using the local chart directory:

```bash
export NAMESPACE=dsx-connect
export FS_RELEASE=filesystem

cp docs/dsx-connect-2/deployment/examples/filesystem-connector-values.yaml \
  /tmp/filesystem-connector-values.yaml

helm upgrade --install "$FS_RELEASE" \
  ./connectors/filesystem/deploy/helm \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f /tmp/filesystem-connector-values.yaml \
  --set image.repository=local/dsx-connect/filesystem-connector \
  --set image.tag=dev \
  --set image.pullPolicy=IfNotPresent
```

The filesystem `hostPath` must exist on the Kubernetes node where the pod runs.
For Colima, create it inside the Colima VM or start Colima with the host path mounted.

## Start a Single Local DSXA

DSX-Connect 2 can start a single DSXA container in the local Python runtime.
This is available for local development and lab validation, not through the Kubernetes Helm chart yet.

Create a DSXA env file:

```bash
cat > ~/.dsx-connect-local/dsx-connect-ng/.env.dsxa.local <<'EOF'
APPLIANCE_URL=<your-appliance>.deepinstinctweb.com
TOKEN=<scanner-registration-token>
SCANNER_ID=<scanner-id>
HOST_PORT=15000
FLAVOR=rest,config
NO_SSL=true
# Optional override; otherwise the launcher defaults to dsxconnect/dpa-rocky9:4.2.0.2176.
# DSXA_IMAGE=dsxconnect/dpa-rocky9:4.2.0.2176
EOF
```

Run the local stack with PostgreSQL, RabbitMQ, and DSXA:

```bash
./.venv/bin/python -m dsx_connect_ng.local.dsx_connect_ng_local \
  --with-postgres-docker \
  --with-rabbit-docker \
  --with-dsxa-docker \
  --dsxa-env-file ~/.dsx-connect-local/dsx-connect-ng/.env.dsxa.local \
  foreground
```

The launcher configures DSX-Connect 2 scanner mode automatically:

```text
DSX_CONNECT_NG_SCANNER__MODE=dsxa
DSX_CONNECT_NG_SCANNER__BASE_URL=http://127.0.0.1:15000
```

For Kubernetes deployments, deploy DSXA separately or use an existing DSXA endpoint and set:

```yaml
env:
  DSX_CONNECT_NG_SCANNER__MODE: "dsxa"
  DSX_CONNECT_NG_SCANNER__BASE_URL: "http://<dsxa-host>:15000"
```

## Update a Lab Stack with Helper Scripts

For a persistent lab VM or k3s host, keep environment-specific values files on the VM:

```bash
~/.dsx-connect-lab/
  dsx-connect-values.yaml
  gcs-values.yaml
  filesystem-values.yaml
```

Update all releases using versions from the checked-out repo:

```bash
scripts/dsx-connect-ng/update-lab-stack.sh \
  --namespace dsx-connect \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
  --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
```

Update to explicit released versions:

```bash
scripts/dsx-connect-ng/update-lab-stack.sh \
  --connect-version 2.0.8 \
  --gcs-version 2.0.5 \
  --filesystem-version 2.0.4 \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
  --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
```

Preview without applying:

```bash
scripts/dsx-connect-ng/update-lab-stack.sh \
  --dry-run \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
  --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
```

The helper installs these OCI charts by default:

```text
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart
oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart
oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart
```

## Verify Local Deployment

```bash
helm list -n dsx-connect
kubectl get pods -n dsx-connect
kubectl logs -n dsx-connect deploy/dsx-connect-api
```

Port-forward the API:

```bash
kubectl port-forward -n dsx-connect svc/dsx-connect-api 8091:8091
```

Open:

```text
http://127.0.0.1:8091/
```
