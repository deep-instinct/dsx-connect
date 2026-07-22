# Static Kubernetes Manifests

Some customer environments cannot run Helm in production, even when they can apply Kubernetes YAML with `kubectl`.
For those environments, keep Helm as the source of truth and ship rendered static manifests for the exact DSX-Connect 2 release and values profile.

The customer applies the rendered YAML:

```bash
kubectl apply -f dsx-connect-2.0.13.yaml
```

They do not need Helm on the target cluster.

## Recommended Model

Use Helm charts to generate static manifests outside the customer cluster:

1. Choose a released chart version.
2. Choose an environment-specific values file.
3. Render the chart with `helm template`.
4. Review the YAML.
5. Deliver the YAML bundle to the customer.
6. Customer applies the YAML with `kubectl apply`.

Do not hand-maintain a separate static manifest tree.
That creates drift from the supported Helm chart.

## Render DSX-Connect 2

Render the DSX-Connect 2 control-plane chart:

```bash
export RELEASE=dsx-connect
export NAMESPACE=dsx-connect
export DSX_CONNECT_VERSION=2.0.13

helm template "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  -f dsx-connect-values.yaml \
  > "dsx-connect-${DSX_CONNECT_VERSION}.yaml"
```

The output contains normal Kubernetes resources such as Deployments, Services, ConfigMaps, and PersistentVolumeClaims.

Apply it:

```bash
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "dsx-connect-${DSX_CONNECT_VERSION}.yaml"
```

Check rollout:

```bash
kubectl get pods -n "$NAMESPACE"
kubectl rollout status deploy/dsx-connect-api -n "$NAMESPACE"
```

## Render Connectors

Render connector charts the same way.
For example, Google Cloud Storage:

```bash
export NAMESPACE=dsx-connect
export GCS_VERSION=2.0.9

helm template gcs \
  oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version "$GCS_VERSION" \
  --namespace "$NAMESPACE" \
  -f gcs-values.yaml \
  > "google-cloud-storage-connector-${GCS_VERSION}.yaml"
```

Apply it:

```bash
kubectl apply -f "google-cloud-storage-connector-${GCS_VERSION}.yaml"
kubectl rollout status deploy/gcs-google-cloud-storage-connector -n "$NAMESPACE"
```

## Secrets

Prefer creating Secrets separately from the rendered manifest bundle.
This keeps customer credentials out of static release artifacts.

Example:

```bash
kubectl create secret generic gcp-sa \
  -n dsx-connect \
  --from-file=service-account.json=/path/to/service-account.json
```

Then reference the Secret from the values file before rendering the connector chart.

For DSX-Connect 2 runtime Secrets:

```bash
kubectl create secret generic dsx-connect-runtime-env \
  -n dsx-connect \
  --from-literal='DSX_CONNECT_NG_POSTGRES__URL=postgresql://user:password@postgres.example:5432/dsx_connect_2' \
  --from-literal='DSX_CONNECT_NG_RABBITMQ__URL=amqp://user:password@rabbitmq.example:5672/%2F'
```

## Upgrades

Static-manifest upgrades are still versioned.
Render a new manifest for the new chart version and values file:

```bash
export DSX_CONNECT_VERSION=2.0.13

helm template "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  -f dsx-connect-values.yaml \
  > "dsx-connect-${DSX_CONNECT_VERSION}.yaml"

kubectl apply -f "dsx-connect-${DSX_CONNECT_VERSION}.yaml"
```

Kubernetes updates changed resources in place and rolls Deployments when pod templates change.

## Teardown

Delete using the same manifest that was applied:

```bash
kubectl delete -f dsx-connect-2.0.13.yaml
```

Use care with PersistentVolumeClaims.
Deleting a manifest that includes PVCs may delete durable state depending on storage class and reclaim policy.

## Operational Notes

Static manifests are best for controlled customer environments where Helm is blocked by policy.
They are less flexible than Helm for day-to-day operations:

* no `helm upgrade --install`
* no Helm release history
* no Helm rollback
* no values diff at deployment time

For customers that can run Helm in CI but not in production, render the manifests in CI and promote the generated YAML through the customer's normal change-control process.
