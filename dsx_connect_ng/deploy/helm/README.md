# DSX-Connect Helm Deployment

This chart deploys DSX-Connect v2. The Python package is still named
`dsx_connect_ng` internally, but chart names, images, and Kubernetes resources
use the product-facing `dsx-connect` name.

## Local k3s API-Only Smoke Deploy

Build a local image and load it into the active Docker runtime:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag dev \
  --registry local/dsx-connect \
  --load
```

Deploy the API-only local profile. This uses in-memory backends and does not
start Postgres, RabbitMQ, or workers:

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local.yaml
```

Expose the API and operator console locally:

```bash
kubectl port-forward \
  -n dsx-connect \
  svc/dsx-connect-api \
  8091:8091
```

Then open `http://127.0.0.1:8091/api/v1/ui/`.

## Local k3s Full-Stack Deploy

Use this profile when you want the local cluster to run the API, Postgres,
RabbitMQ, and all workers in one Helm release:

```bash
scripts/dsx-connect-ng/build-image.sh \
  --tag dev \
  --registry local/dsx-connect \
  --load
```

```bash
scripts/dsx-connect-ng/deploy-k3s.sh \
  --tag dev \
  --registry local/dsx-connect \
  --release dsx-connect \
  --namespace dsx-connect \
  -f dsx_connect_ng/deploy/helm/values-local-stack.yaml
```

This profile creates:

- `deployment/dsx-connect-api`
- `deployment/dsx-connect-postgres`
- `deployment/dsx-connect-rabbitmq`
- `deployment/dsx-connect-relay`
- `deployment/dsx-connect-scan`
- `deployment/dsx-connect-policy`
- `deployment/dsx-connect-remediation`
- `deployment/dsx-connect-result-sink`
- `deployment/dsx-connect-dianna`

The local stack uses `emptyDir` storage for Postgres and RabbitMQ by default.
That keeps local iteration simple, but data is removed when the pods are
deleted.

## Runtime Profile

`values.yaml` is intentionally small and uses in-memory backends with only the
API enabled. `values-local-stack.yaml` is for a self-contained local cluster.
Use `values-runtime.example.yaml` as a starting point when production-like
Postgres and RabbitMQ services are managed outside this chart:

```bash
helm upgrade --install dsx-connect dsx_connect_ng/deploy/helm \
  --namespace dsx-connect \
  --create-namespace \
  -f dsx_connect_ng/deploy/helm/values-runtime.example.yaml
```

The runtime example assumes these services already exist in the namespace:

- `postgres:5432`
- `rabbitmq:5672`

Override `DSX_CONNECT_NG_POSTGRES__URL` and `DSX_CONNECT_NG_RABBITMQ__URL` for
the target environment.

## Packaging

Package the chart locally:

```bash
scripts/dsx-connect-ng/package-chart.sh \
  --destination /tmp/dsx-connect-charts
```

Push to an OCI chart repository:

```bash
scripts/dsx-connect-ng/package-chart.sh \
  --push oci://registry-1.docker.io/dsxconnect
```
