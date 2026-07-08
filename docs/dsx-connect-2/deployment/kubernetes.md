# Deploy DSX-Connect 2 with Helm

This page covers the DSX-Connect 2 control plane.
Connector deployment is covered separately in [Deploy connectors](connectors.md).

## Build the Image

For local k3s or Colima testing, build and load the image into the local Docker image store:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag dev \
  --registry local/dsx-connect \
  --load
```

For a registry-backed deployment, build and push instead:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag 2.0.1 \
  --registry dsxconnect \
  --push \
  --platform linux/amd64,linux/arm64
```

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

Use this mode when validating the API pod, service, image, and UI shell.
Do not use it for connector registration or scan workflow validation.

## Deploy Full-Stack Local Mode

Full-stack local mode enables PostgreSQL, RabbitMQ, and all workers.
Use this for connector registration, asset inventory, protection workflows, scan dispatch, and result processing.

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local-stack.yaml
```

The local stack values file enables:

* PostgreSQL
* RabbitMQ
* relay worker
* scan worker
* policy worker
* remediation worker
* result sink worker
* DIANNA worker

It also sets:

```yaml
DSX_CONNECT_NG__CONTROL_PLANE_BACKEND: postgres
DSX_CONNECT_NG__JOB_BUS_BACKEND: rabbitmq
DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA: "true"
DSX_CONNECT_NG_SCANNER__MODE: stub
DSX_CONNECT_NG_READERS__DEFAULT_STRATEGY: native
```

## Update a Lab Stack from Released Charts

For a persistent lab VM or k3s host, keep environment-specific values files on the VM and update the stack from released OCI Helm charts.
This avoids local image builds and does not require GitHub Actions to reach into the lab.

Example VM layout:

```bash
~/.dsx-connect-lab/
  dsx-connect-values.yaml
  gcs-values.yaml
  filesystem-values.yaml
```

Update all three releases using the versions in the checked-out repo:

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
  --connect-version 2.0.1 \
  --gcs-version 2.0.2 \
  --filesystem-version 2.0.2 \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
  --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
```

Update only DSX-Connect and GCS:

```bash
scripts/dsx-connect-ng/update-lab-stack.sh \
  --skip-filesystem \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml
```

Preview without applying:

```bash
scripts/dsx-connect-ng/update-lab-stack.sh \
  --dry-run \
  --core-values ~/.dsx-connect-lab/dsx-connect-values.yaml \
  --gcs-values ~/.dsx-connect-lab/gcs-values.yaml \
  --filesystem-values ~/.dsx-connect-lab/filesystem-values.yaml
```

The script installs these OCI charts by default:

```text
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart
oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart
oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart
```

## Open the Operator Console

Port-forward the API service:

```bash
kubectl port-forward -n dsx-connect svc/dsx-connect-api 8091:8091
```

Open:

```text
http://127.0.0.1:8091/api/v1/ui/
```

## Check Runtime Status

List pods:

```bash
kubectl get pods -n dsx-connect
```

Expected full-stack pods include:

* `dsx-connect-api`
* `dsx-connect-postgres`
* `dsx-connect-rabbitmq`
* `dsx-connect-relay`
* `dsx-connect-scan`
* `dsx-connect-policy`
* `dsx-connect-remediation`
* `dsx-connect-result-sink`
* `dsx-connect-dianna`

Check logs for a worker:

```bash
kubectl logs -n dsx-connect deploy/dsx-connect-relay
```

## Tear Down

Remove the Helm release:

```bash
helm uninstall dsx-connect -n dsx-connect
```

If you used the local stack values with non-persistent PostgreSQL and RabbitMQ, runtime state is removed with the pods.

## Production Notes

The local stack is intentionally convenient.
Before production use, plan for:

* persistent PostgreSQL and RabbitMQ storage
* external managed PostgreSQL or RabbitMQ where appropriate
* secrets instead of inline credentials
* ingress and TLS
* DSX-Connect authentication
* scanner mode and DSXA reachability
* resource requests and limits
* worker replica counts and queue capacity
* image registry and pull-secret configuration
