# Deploying DSX-Connect 2 (Helm)

This Helm chart deploys the DSX-Connect 2 control plane:

* API and Operator Console
* PostgreSQL-backed control plane state
* RabbitMQ-backed job dispatch
* relay, scan, policy, remediation, result sink, and DIANNA workers

Connector deployment is covered separately in [Deploy connectors](connectors/index.md).
Development builds and helper-script workflows are covered in [Development deployment](development.md).

This guide focuses on standard Kubernetes deployment with `kubectl` and Helm.

For customer environments that cannot run Helm in production, render the same charts to YAML and apply them with `kubectl`.
See [Static Kubernetes Manifests](static-manifests.md).

## Prerequisites

* Kubernetes 1.19+
* Helm 3.8+ with OCI registry support
* `kubectl` configured for the target cluster
* Network access from the cluster to the DSX-Connect 2 image registry
* Access to the DSX-Connect 2 chart:

```text
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart
```

For local Kubernetes guidance, see [Lightweight K8S Recommendations](../../reference/installations/kubernetes.md).

## Naming Conventions

The examples use:

| Name | Value |
| --- | --- |
| Helm release | `dsx-connect` |
| Namespace | `dsx-connect` |
| Chart version | `2.0.13` |

Set these variables once for the shell session:

```bash
export RELEASE=dsx-connect
export NAMESPACE=dsx-connect
export DSX_CONNECT_VERSION=2.0.13
```

When examples show a release name or namespace, they use these values.

## Chart vs Image Versioning

DSX-Connect 2 release builds publish both:

* a container image, such as `dsxconnect/dsx-connect:2.0.13`
* an OCI Helm chart, such as `dsxconnect/dsx-connect-chart --version 2.0.13`

The chart `appVersion` is intended to match the DSX-Connect image version for release builds.
If you deploy a released chart without overriding `image.tag`, the chart uses the matching released image tag.

Pin the chart version for repeatable deployments:

```bash
helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  -f dsx-connect-values.yaml
```

For production and lab environments, keep an environment-specific values file in source control or on the target VM, and pin the chart version.

## One-Time Bootstrap

Before deploying DSX-Connect 2, create the namespace and any Secrets required by the features you enable.

### Create namespace

Create the namespace:

```bash
kubectl create namespace "$NAMESPACE"
```

### Create required secrets

The local full-stack example values shown below do not require Kubernetes Secrets.
Secrets become required when you enable private registries, externally managed services, scanner authentication, or other sensitive settings.

| Feature you enable | Values setting | Secret required | Example |
| --- | --- | --- | --- |
| Private image registry | `imagePullSecrets` | Docker registry Secret | `dsx-registry` |
| Sensitive DSX-Connect 2 env vars | `envSecretRefs` | Generic Secret containing `DSX_CONNECT_NG_*` keys | `dsx-connect-runtime-env` |
| External PostgreSQL | `envSecretRefs` or external secret workflow | Secret containing `DSX_CONNECT_NG_POSTGRES__URL` | `dsx-connect-runtime-env` |
| External RabbitMQ | `envSecretRefs` or external secret workflow | Secret containing `DSX_CONNECT_NG_RABBITMQ__URL` | `dsx-connect-runtime-env` |
| DSXA auth token | `envSecretRefs` | Secret containing `DSX_CONNECT_NG_SCANNER__DSXA_AUTH_TOKEN` | `dsx-connect-runtime-env` |

Create an image pull Secret only if your image registry requires authentication:

```bash
kubectl create secret docker-registry dsx-registry \
  --namespace "$NAMESPACE" \
  --docker-server=registry-1.docker.io \
  --docker-username="<registry-user>" \
  --docker-password="<registry-token>"
```

Then reference it from values:

```yaml
imagePullSecrets:
  - dsx-registry
```

Create a runtime env Secret when sensitive values should not be placed directly in a values file:

```bash
kubectl create secret generic dsx-connect-runtime-env \
  --namespace "$NAMESPACE" \
  --from-literal='DSX_CONNECT_NG_POSTGRES__URL=postgresql://user:password@postgres.example:5432/dsx_connect_2' \
  --from-literal='DSX_CONNECT_NG_RABBITMQ__URL=amqp://user:password@rabbitmq.example:5672/%2F' \
  --from-literal='DSX_CONNECT_NG_SCANNER__DSXA_AUTH_TOKEN=<scanner-auth-token>'
```

Then reference it from values:

```yaml
envSecretRefs:
  - dsx-connect-runtime-env
```

Connector-specific secrets, such as GCS service account JSON credentials, are covered in [Deploy connectors](connectors/index.md).

## Deploy DSX-Connect 2

For the full list of chart values, inspect the released chart defaults:

```bash
helm show values \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION"
```

### Method 1: OCI and Command-Line Overrides

This method is useful for short-lived testing where you do not want to create a values file.
It deploys the full stack with in-cluster PostgreSQL and RabbitMQ and uses the stub scanner.

```bash
helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --set postgresql.enabled=true \
  --set postgresql.persistence.enabled=false \
  --set rabbitmq.enabled=true \
  --set rabbitmq.persistence.enabled=false \
  --set workers.relay.enabled=true \
  --set workers.scan.enabled=true \
  --set workers.policy.enabled=true \
  --set workers.remediation.enabled=true \
  --set workers.resultSink.enabled=true \
  --set workers.dianna.enabled=true \
  --set-string env.DSX_CONNECT_NG__ENVIRONMENT=dev \
  --set-string env.DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=postgres \
  --set-string env.DSX_CONNECT_NG__JOB_BUS_BACKEND=rabbitmq \
  --set-string env.DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA=true \
  --set-string env.DSX_CONNECT_NG_POSTGRES__URL=postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2 \
  --set-string env.DSX_CONNECT_NG_RABBITMQ__URL=amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F \
  --set-string env.DSX_CONNECT_NG_SCANNER__MODE=stub \
  --set-string env.DSX_CONNECT_NG_READERS__DEFAULT_STRATEGY=native
```

To use a reachable DSXA scanner instead of the stub scanner, replace the scanner values:

```bash
--set-string env.DSX_CONNECT_NG_SCANNER__MODE=dsxa \
--set-string env.DSX_CONNECT_NG_SCANNER__BASE_URL=http://<dsxa-host>:15000
```

The DSXA URL must be reachable from inside the Kubernetes cluster, not only from your laptop.

### Method 2: Values File

This is the most common and recommended method for managing deployments.

First, start by pulling the latest dsx-connect helm chart (--untar will unpack the chart):
```
helm pull oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --untar
```
or, if using a specific chart version:
```
helm pull oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version <x.x.x> --untar
```

The `--untar` flag will unzip the archive downloaded, as a convenience.  After `helm pull --untar`, the chart folder looks like:

```text
dsx-connect/
  Chart.yaml
  values.yaml
  templates/
    ...
```

Typically one should copy `values.yaml`, or one of the DSX-Connect 2 example values files, and edit the copy.  This makes it easy to return back to defaults,
experiment with types of deployments, and/or pin specific environments and versions of deployments (e.g. `values-staging.yaml`, `values-prod.yaml`, `values-prod-us-west-1.yaml`, `values-prod-2.0.3.yaml`, etc...)

The DSX-Connect 2 Helm chart does not currently deploy DSXA in-cluster.
It can run with the stub scanner for control-plane validation, or it can point at an external DSXA scanner that is reachable from inside Kubernetes.
For a local one-command stack that starts a single DSXA container alongside DSX-Connect 2 services, use the local runtime described in [Development deployment](development.md#start-a-single-local-dsxa).

Configure your `values.yaml`, setting variables as needed.
Use `helm show values` for the complete chart value reference.
Install the chart, referencing your values file with the `-f` flag.
The `.` assumes you are currently in the `dsx-connect/` chart directory.

```bash
helm upgrade --install dsx-connect . -f my-dsx-connect-values.yaml -n dsx-connect
```

This is the recommended method for lab, staging, and production deployments.
Start from the full-stack example values file:

```bash
cp docs/dsx-connect-2/deployment/examples/dsx-connect-full-stack-values.yaml \
  dsx-connect-values.yaml
```

#### Full example DSXA values file:

```yaml
# Full-stack DSX-Connect 2 values file.
# This profile runs the API, PostgreSQL, RabbitMQ, and all workers in one Helm release.

# API deployment tuning.
api:
  # Number of API pods.
  replicaCount: 1
  # Number of Uvicorn worker processes inside each API pod.
  workers: 1

env:
  # Free-form environment label shown in logs and diagnostics.
  DSX_CONNECT_NG__ENVIRONMENT: "dev"

  # Use the in-cluster PostgreSQL and RabbitMQ services enabled below.
  DSX_CONNECT_NG__CONTROL_PLANE_BACKEND: "postgres"
  DSX_CONNECT_NG__JOB_BUS_BACKEND: "rabbitmq"

  # Auto-apply the database schema from the API pod on startup.
  # For stricter production workflows, handle migrations separately and set this to "false".
  DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA: "true"
  DSX_CONNECT_NG_POSTGRES__URL: "postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2"
  DSX_CONNECT_NG_RABBITMQ__URL: "amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F"

  # DSXA scanner mode.
  # Use "dsxa" when the cluster can reach a real DSXA scanner.
  # Use "stub" only for control-plane smoke tests where no real scanning is required.
  DSX_CONNECT_NG_SCANNER__MODE: "dsxa"
  DSX_CONNECT_NG_SCANNER__BASE_URL: "http://<dsxa-host>:15000"

  # Worker reader mode. "native" lets workers read content through registered connectors.
  DSX_CONNECT_NG_READERS__DEFAULT_STRATEGY: "native"

postgresql:
  # Embedded PostgreSQL is convenient for lab and local validation.
  # For production, use an externally managed PostgreSQL service and set enabled=false.
  enabled: true
  persistence:
    # false uses emptyDir and loses data when the pod is deleted.
    # Set true and configure storage for durable lab or production use.
    enabled: false

rabbitmq:
  # Embedded RabbitMQ is convenient for lab and local validation.
  # For production, use an externally managed RabbitMQ service and set enabled=false.
  enabled: true
  persistence:
    # false uses emptyDir and loses queue state when the pod is deleted.
    # Set true and configure storage for durable lab or production use.
    enabled: false

workers:
  relay:
    enabled: true
    # Number of relay pods.
    replicaCount: 1
    # Relay pulls pending outbox records and publishes RabbitMQ work messages.
    args:
      - "--batch-size"
      - "100"
      - "--poll-interval-seconds"
      - "0.25"
      # Backpressure guard: stop publishing new scan items when active scan work is above this count.
      # Remove or raise this when increasing scan-worker capacity.
      - "--max-active-scan-items"
      - "1000"

  scan:
    enabled: true
    # Number of scan worker pods.
    replicaCount: 1
    # Scan worker concurrency is controlled by both pod count and these args.
    # Effective parallelism is roughly replicaCount * prefetch-count, bounded by DSXA and connector read speed.
    args:
      # Number of RabbitMQ scan messages each scan worker may hold in flight.
      - "--prefetch-count"
      - "10"
      # Batch coarse scan-only completions before persisting terminal item state.
      - "--scan-only-completion-batch-size"
      - "10"
      - "--scan-only-completion-flush-interval-seconds"
      - "1.0"
      # Collect up to this many scan-only messages into an async read/scan batch.
      - "--scan-batch-window-size"
      - "100"
      - "--scan-batch-window-wait-seconds"
      - "0.5"
      # Maximum concurrent read/scan coroutines inside each scan batch.
      # Set to 0 to use prefetch-count.
      - "--scan-batch-concurrency"
      - "6"
      # Ack messages after scan completion is buffered.
      # Options: completed, scanned, accepted.
      - "--scan-batch-ack-mode"
      - "scanned"
      - "--scan-batch-trust-items"

  policy:
    enabled: true
    replicaCount: 1
    args:
      # Number of policy messages each policy worker may process concurrently.
      - "--prefetch-count"
      - "100"

  remediation:
    enabled: true
    replicaCount: 1
    args:
      # Number of remediation messages each remediation worker may process concurrently.
      - "--prefetch-count"
      - "5"

  resultSink:
    enabled: true
    replicaCount: 1
    args:
      # Number of result-sink messages each result-sink worker may process concurrently.
      - "--prefetch-count"
      - "10"

  dianna:
    enabled: true
    replicaCount: 1
    args:
      # Number of DIANNA messages each DIANNA worker may process concurrently.
      - "--prefetch-count"
      - "5"
```

Install the chart with your values file:

```bash
helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f dsx-connect-values.yaml
```

For a persistent lab VM, keep this values file on the VM, edit it for the environment, and rerun the same Helm command when updating to a new released version.

### Method 3: GitOps

For production, store environment-specific values files in a GitOps repository and let Argo CD, Flux, or another controller apply the Helm release.

The GitOps repository should pin:

* chart repository: `oci://registry-1.docker.io/dsxconnect/dsx-connect-chart`
* chart version, such as `2.0.3`
* environment-specific values
* any required Secrets through your chosen secret-management workflow

This gives you a repeatable, auditable deployment path without manual `helm upgrade` commands.

## Post-Deploy

### Verify the Deployment

Check the Helm release:

```bash
helm list -n "$NAMESPACE"
helm status "$RELEASE" -n "$NAMESPACE"
```

Check pods:

```bash
kubectl get pods -n "$NAMESPACE"
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

Check logs:

```bash
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-api
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-relay
```

### Access the Operator Console

For local testing, port-forward the API service:

```bash
kubectl port-forward -n "$NAMESPACE" svc/dsx-connect-api 8091:8091
```

Open:

```text
http://127.0.0.1:8091/
```

To expose the port from a lab VM to another machine on the same network, bind to all interfaces:

```bash
kubectl port-forward -n "$NAMESPACE" svc/dsx-connect-api 8091:8091 --address 0.0.0.0
```

Then open:

```text
http://<cluster-host-ip>:8091/
```

Port-forwarding stops when the command exits.
For longer-lived access, use an ingress or load balancer appropriate for the cluster.

### Establish Ingress

The DSX-Connect chart can manage the API/UI `Ingress` resource. Ingress is disabled by default because clusters differ on ingress controller, TLS, DNS, WAF, and load-balancer strategy.

For k3s with Traefik, use `ingress.className: traefik`. See [Reference > Traefik](../../reference/traefik.md) for k3s Traefik setup, HTTP-to-HTTPS redirects, and TLS-secret examples.

Add this to your DSX-Connect values file:

```yaml
ingress:
  enabled: true
  className: traefik
  hosts:
    - host: dsx-connect.10.2.4.103.nip.io
      paths:
        - path: /
          pathType: Prefix
```

Apply the chart with the updated values:

```bash
helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f dsx-connect-values.yaml
```

Verify the ingress:

```bash
kubectl get ingress -n "$NAMESPACE"
kubectl describe ingress -n "$NAMESPACE" dsx-connect-api
```

Open:

```text
http://dsx-connect.10.2.4.103.nip.io/
```

If Traefik redirects HTTP to HTTPS, create a TLS secret and add it to the same values file:

```bash
kubectl create secret tls dsx-connect-tls \
  -n "$NAMESPACE" \
  --cert=/path/to/tls.crt \
  --key=/path/to/tls.key
```

Then add `tls` to the ingress values:

```yaml
ingress:
  enabled: true
  className: traefik
  hosts:
    - host: dsx-connect.10.2.4.103.nip.io
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: dsx-connect-tls
      hosts:
        - dsx-connect.10.2.4.103.nip.io
```

## Upgrade

Update the pinned chart version and run Helm again:

```bash
export DSX_CONNECT_VERSION=2.0.13

helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  -f dsx-connect-values.yaml
```

## Uninstall

Remove the Helm release:

```bash
helm uninstall "$RELEASE" -n "$NAMESPACE"
```

If you used the local example values with non-persistent PostgreSQL and RabbitMQ, runtime state is removed with the pods.

## Troubleshooting

If pods are running but DSX-Connect components cannot reach each other through Kubernetes services, first verify cluster networking before changing DSX-Connect values.

Common signs include:

* API or worker logs show connection timeouts to `dsx-connect-postgres:5432`.
* Connectors cannot register with `http://dsx-connect-api:8091`.
* Services and endpoints exist, but traffic to those endpoints times out.
* `kubectl logs` or `kubectl exec` fails with kubelet `:10250` timeouts.

For a GKE-focused diagnostic walkthrough, see [Case Study: GKE Cluster Networking Troubleshooting](../../case-studies/gke-cluster-networking-troubleshooting.md).

## Next Steps

* Deploy a repository connector: [Deploy connectors](connectors/index.md)
* Review packaging and release flow: [Packaging releases](../packaging-releases.md)
* For local image builds and helper scripts: [Development deployment](development.md)
