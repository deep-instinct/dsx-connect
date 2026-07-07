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
