# AWS S3 Connector — Helm Deployment

Deploy the `aws-s3-connector-chart` (under `connectors/aws_s3/deploy/helm`) using the steps below, whether you work directly from the repo or from the OCI registry.

## Prerequisites

- Kubernetes 1.19+ cluster with `kubectl` access.
- Helm 3.2+.
- Access to `oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart`.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

Create the AWS credentials Secret before installing:

```bash
kubectl create secret generic aws-credentials \
  --from-literal=AWS_ACCESS_KEY_ID=<key> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<secret>
```

(`connectors/aws_s3/deploy/helm/aws-secret.yaml` contains a template if you prefer to edit/apply a manifest.)

## Configuration

### Required settings

- `env.DSXCONNECTOR_ASSET`: target bucket or `bucket/prefix`.
- `env.DSXCONNECTOR_FILTER`: optional rsync-style include/exclude set (see [Filter reference](../../reference/filters.md)).
- `env.DSXCONNECTOR_DISPLAY_NAME`: friendly label in the dsx-connect UI.
- `env.DSXCONNECTOR_ITEM_ACTION` plus `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`: remediation options.
- `workers`: Uvicorn workers per pod (default 1).
- `replicaCount`: number of pods (default 1).

Filters follow rsync semantics (`?`, `*`, `**`, `+`, `-`).

### dsx-connect endpoint

Defaults to `http://dsx-connect-api` (or `https://dsx-connect-api` when TLS enabled). Override via `env.DSXCONNECTOR_DSX_CONNECT_URL` if dsx-connect is exposed elsewhere.

### Authentication (Optional)
See [Using DSX-Connect Authentication](authentication.md).

### SSL/TLS (Optional)
See [Deploying with SSL/TLS](tls.md).

## Deployment

### Method 1 – OCI chart with CLI overrides (fastest)

```bash
helm install aws-invoices-dev oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart \
  --version <chart-version> \
  --set env.DSXCONNECTOR_ASSET=my-bucket \
  --set-string env.DSXCONNECTOR_FILTER="" \
  --set-string image.tag=<connector-version>
```

For pulled-chart installs and GitOps/production patterns (values files, Flux/Argo), see [Advanced Connector Deployment](advanced-connector-deployment.md).

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/aws-s3-connector -f
```

## Scaling & tuning

- Raise `workers` for more concurrent `read_file` responses within a pod.
- Increase `replicaCount` for HA or to fan out item actions; each pod registers separately.
- Keep AWS throttling in mind when increasing concurrency; adjust filters to limit scope.

See `connectors/aws_s3/deploy/helm/values.yaml` for the exhaustive parameter reference.
