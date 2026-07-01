# Advanced Connector Deployment (Kubernetes)

This page covers the “production-style” deployment patterns that apply to every connector chart:

- **Pulled chart + local `values.yaml`** (inspect/customize a chart before installing)
- **GitOps** (commit values/manifests and let a controller reconcile)

Each connector guide includes a quick “Method 1” install for fast validation. Use this page when you want repeatable, reviewable, environment-specific deployments.

## Prerequisites
- Helm 3.x and `kubectl`
- Access to the connector charts in OCI (`oci://registry-1.docker.io/dsxconnect/...`)
- Secrets created via Kubernetes-native approaches (see [Kubernetes Secrets and Credentials](index.md#kubernetes-secrets-and-credentials))

## Method 2 — Pull the chart and edit values locally
This is a good middle ground when you want to inspect defaults or customize resources before installing.

1) Pull and untar:
```bash
CHART_OCI="oci://registry-1.docker.io/dsxconnect/<connector>-connector-chart"
CHART_VERSION="<chart-version>"

helm pull "$CHART_OCI" --version "$CHART_VERSION" --untar
cd <connector>-connector-chart
```

2) Create an environment values file, for example `values-dev.yaml`:
```yaml
env:
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8586"
  DSXCONNECTOR_ASSET: "<asset>"

# Most charts support this (or similar) to import env from Secrets:
# envSecretRefs:
#   - my-connector-env

image:
  tag: "<connector-version>"

replicaCount: 1
workers: 1
```

3) Install from the extracted chart directory:
```bash
helm upgrade --install <release-name> . -f values-dev.yaml -n <namespace> --create-namespace
```

## Method 3 — GitOps / production style
For production, prefer committing **non-secret** configuration to git and sourcing secrets from a secrets manager (or encrypted secret manifests).

### Option A: Commit only values and run Helm in CI
Keep a `values-prod.yaml` per connector/environment and run:
```bash
helm upgrade --install <release-name> oci://registry-1.docker.io/dsxconnect/<connector>-connector-chart \
  --version <chart-version> \
  -f values-prod.yaml \
  -n <namespace>
```

### Option B: Flux / Argo CD (Helm controller)
Define a `HelmRelease`/`Application` that pins the chart version and references committed values.

Flux example (illustrative):
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: <release-name>
  namespace: <namespace>
spec:
  interval: 5m
  chart:
    spec:
      chart: <connector>-connector-chart
      sourceRef:
        kind: OCIRepository
        name: dsxconnect
      version: <chart-version>
  valuesFrom:
    - kind: Secret
      name: <connector>-env
      valuesKey: values.yaml
  values:
    image:
      tag: "<connector-version>"
```

Your GitOps controller should be the only thing applying changes; operators update git and the controller reconciles.

## GitHub Actions deployment to k3s

The repository includes a manual workflow for connector deployment:

```text
Deploy Connector to k3s
```

This workflow is intended for a lab or integration cluster that is reachable from a GitHub self-hosted runner. GitHub does not need inbound network access to the cluster. The runner opens an outbound connection to GitHub, receives the job, and runs `helm`/`kubectl` locally.

Expected runner labels:

```text
self-hosted
k3s
dsx-connect-lab
```

The runner host must have:

- outbound HTTPS access to GitHub
- `kubectl` configured for the target k3s cluster
- Helm installed
- access to any values files referenced by the workflow
- required Kubernetes Secrets already applied in the target namespace

The deploy workflow has a `wait` input. Keep `wait=true` when DSX Connect is running and connector readiness should be enforced. Use `wait=false` for connector-only smoke tests before DSX Connect is deployed; in that mode the connector pod can start and pass `/healthz`, while `/readyz` remains `503` until registration succeeds.

Example connector-only smoke deploy:

```text
connector: google_cloud_storage
tag: 0.5.55
release_name: gcs
namespace: dsx-connect
image_registry: dsxconnect
values_file: connectors/google_cloud_storage/deploy/helm/examples/values-lab.example.yaml
wait: false
```

## A note on secrets and `--set`
- Avoid putting real secrets in `helm --set ...` or `kubectl create secret --from-literal ...` in shared environments; these often leak into shell history and CI logs.
- Prefer Secrets referenced by the chart (for example, `envSecretRefs`) and a secrets manager integration (External Secrets Operator), or encrypted secrets with SOPS/Sealed Secrets.
