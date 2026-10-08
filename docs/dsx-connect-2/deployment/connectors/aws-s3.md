# AWS S3 Connector

The AWS S3 connector gives DSX-Connect 2 access to Amazon S3 buckets and S3-compatible object stores.
It discovers buckets, enumerates and reads objects for scanning, applies remediation actions, and can receive S3 event notifications for continuous protection.

Repository credentials stay in the connector.
DSX-Connect scan workers read object content through the connector's proxy endpoint, so they never need AWS access.

---

## Prerequisites

* A running DSX-Connect 2 deployment. See [Deploying DSX-Connect Core](../kubernetes.md).
* An AWS IAM user or role with access to the buckets you want to protect.
* An access key for that identity. The chart reads `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from a Kubernetes Secret.

### IAM permissions

| Purpose | Actions |
| --- | --- |
| Bucket discovery in the Operator Console | `s3:ListAllMyBuckets` |
| Enumerate and scan objects | `s3:ListBucket`, `s3:GetObject` |
| Move or copy remediation | `s3:PutObject`, `s3:DeleteObject` |
| Delete remediation | `s3:DeleteObject` |
| Tag remediation | `s3:PutObjectTagging` |
| Governed file delivery (write) | `s3:PutObject` |

A scan-only policy for specific buckets:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Discover",
      "Effect": "Allow",
      "Action": "s3:ListAllMyBuckets",
      "Resource": "*"
    },
    {
      "Sid": "ListProtectedBuckets",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": ["arn:aws:s3:::example-bucket"]
    },
    {
      "Sid": "ReadObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": ["arn:aws:s3:::example-bucket/*"]
    }
  ]
}
```

Add the remediation actions to the object statement for buckets where DSX-Connect may move, tag, or delete objects.
Without `s3:ListAllMyBuckets`, discovery reports `permission_denied`; you can still protect a bucket set in `DSXCONNECTOR_ASSET`.

---

## Full Scan and Monitoring Guidance

Full scans establish baseline coverage across a bucket or prefix.
Because the bucket stays live during scanning, treat a full scan as best-effort enumeration rather than a point-in-time snapshot.

S3 event notifications keep coverage current by triggering scans for new and overwritten objects.
Run full scans during quieter periods where possible, and keep monitoring enabled for steady-state protection.

---

## Deploy

### Create the AWS credentials Secret

The chart expects a Secret named `aws-credentials` by default, with keys `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`:

```bash
export NAMESPACE=dsx-connect

kubectl create secret generic aws-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=AWS_ACCESS_KEY_ID='<access-key-id>' \
  --from-literal=AWS_SECRET_ACCESS_KEY='<secret-access-key>'
```

To use a different Secret name, set `secrets.name`.

For temporary credentials, or to set a default region, add the extra variables in a second Secret and project it with `envSecretRefs`:

```bash
kubectl create secret generic aws-session \
  --namespace "$NAMESPACE" \
  --from-literal=AWS_SESSION_TOKEN='<session-token>' \
  --from-literal=AWS_DEFAULT_REGION='us-east-1'
```

```yaml
envSecretRefs:
  - aws-session
```

Session tokens expire, so temporary credentials suit short tests only.
Long-running deployments need a credential that does not expire, or a process that refreshes the Secret and restarts the connector.

### Install

=== "Quick Install"

    Minimal install using Helm CLI overrides:

    ```bash
    export NAMESPACE=dsx-connect
    export S3_VERSION=0.5.60

    helm upgrade --install s3 \
      oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart \
      --version "$S3_VERSION" \
      --namespace "$NAMESPACE" \
      --set-string env.DSXCONNECTOR_REGISTER_WITH_CORE=false \
      --set-string env.DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true \
      --set-string env.DSXCONNECTOR_DSX_CONNECT_URL=http://dsx-connect-api:8091 \
      --set-string env.DSXCONNECTOR_INSTANCE_ID=s3-local-1 \
      --set-string env.DSXCONNECTOR_NG_PLATFORM=s3 \
      --set-string env.DSXCONNECTOR_NG_PLATFORM_KEY=demo-aws-account \
      --set secrets.name=aws-credentials
    ```

    !!! note "--version"
        The version is the chart version. Removing it installs the latest chart.

=== "values.yaml Install"

    Use a values file for production and GitOps workflows:

    ```yaml
    env:
      LOG_LEVEL: "info"
      DSXCONNECTOR_REGISTER_WITH_CORE: "false"
      DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
      DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
      DSXCONNECTOR_INSTANCE_ID: "s3-prod-1"
      DSXCONNECTOR_NG_PLATFORM: "s3"
      DSXCONNECTOR_NG_PLATFORM_KEY: "aws-123456789012"

    secrets:
      name: aws-credentials
    ```

    ```bash
    helm upgrade --install s3 \
      oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart \
      --version "$S3_VERSION" \
      --namespace "$NAMESPACE" \
      -f s3-connector-values.yaml
    ```

`DSXCONNECTOR_DSX_CONNECT_URL` is the DSX-Connect API URL used for registration and heartbeats.
Chart 0.5.60 and earlier can also take a separate `DSXCONNECTOR_DSX_CONNECT_NG_URL`, and later versions `DSXCONNECTOR_DSX_CONNECT_V2_URL`.
All fall back to `DSXCONNECTOR_DSX_CONNECT_URL` when the separate URL is unset, so setting only that variable works across versions.

`DSXCONNECTOR_ASSET` and `DSXCONNECTOR_FILTER` are intentionally omitted.
Protected scopes in the control plane decide what gets scanned.
Set `DSXCONNECTOR_ASSET` only to pin the connector to one bucket; see [Platform Identity and Repository Scope](#platform-identity-and-repository-scope).

### OpenShift

The connector listens on `service.port`, which defaults to `80`.
OpenShift's `restricted-v2` SCC runs pods as a non-root UID that cannot bind ports below 1024, so the pod crash-loops with `permission denied` on bind.
Move it to an unprivileged port:

```yaml
service:
  port: 8080
```

The chart uses `service.port` for the listen port, container port, Service port, and the address the connector registers, so no other change is needed.

If the connector first registered on port 80 and was then moved, DSX-Connect 2.0.34 and later refresh the stored connector address automatically.
On earlier versions, update the integration's `config.reader.proxy` and `config.delivery.proxy` URLs, or scan reads time out against the old port.

---

## Monitoring with S3 Event Notifications

The connector exposes a webhook that accepts S3 event notifications:

```text
POST http://<connector-service>:<port>/aws-s3-connector/webhook/event
```

In-cluster, with release name `s3`, the Service is `s3-aws-s3-connector-chart`.
Each event is submitted to DSX-Connect 2 as a scan job.

The payload is the standard S3 event format:

```json
{
  "Records": [
    {
      "s3": {
        "bucket": { "name": "example-bucket" },
        "object": { "key": "path/to/file.pdf" }
      }
    }
  ]
}
```

S3 cannot call an HTTP endpoint directly.
The usual path is **S3 event notification → AWS Lambda → connector webhook**:

1. Expose the webhook to the Lambda's network. The chart does not create an Ingress for it, despite the `ingressWebhook` values; create your own Ingress, OpenShift Route, or load balancer for the connector Service, and protect it with TLS and network restrictions.
2. Create a Lambda function that forwards the event body to the webhook URL. The connector repository includes a minimal example at `connectors/aws_s3/webhook/lambda_function.py`, which reads the target from the `DSX_CONNECTOR_WEBHOOK_URL` environment variable.
3. On each bucket to monitor, add an event notification for `s3:ObjectCreated:*` that invokes the Lambda function.

### Which events get scanned

The connector processes the first record in each event and then applies these checks:

* If `DSXCONNECTOR_ASSET` is set, events for other buckets are ignored, and events outside the configured prefix or `DSXCONNECTOR_FILTER` are ignored.
* If `DSXCONNECTOR_ASSET` is not set, events for any bucket are submitted.

DSX-Connect 2 attributes an event to a protected scope when the object falls inside one.
Events for buckets without a protected scope are still scanned, without scope attribution.
Control which buckets are monitored by choosing where you add event notifications in AWS, or pin the connector to a single bucket with `DSXCONNECTOR_ASSET`.

---

## Platform Identity and Repository Scope

* `DSXCONNECTOR_NG_PLATFORM` identifies the connector type. For this connector it is always `s3`.
* `DSXCONNECTOR_NG_PLATFORM_KEY` is a stable, operator-chosen key for the boundary this connector represents, such as an AWS account ID, organization, environment, or lab name. It groups the connector in DSX-Connect 2. It does not grant access; access comes from the AWS credentials and IAM.
* Protected scopes in DSX-Connect 2 select the buckets or prefixes to protect.
* `DSXCONNECTOR_ASSET` is an optional `bucket` or `bucket/prefix`. It restricts webhook events to that location and provides the `configured_asset` discovery source, which is useful for single-bucket labs or when `s3:ListAllMyBuckets` is not granted.

Connectors with the same `DSXCONNECTOR_NG_PLATFORM` and `DSXCONNECTOR_NG_PLATFORM_KEY` share one integration in DSX-Connect 2.
Give connectors for different AWS accounts different platform keys.

---

## S3-Compatible Storage

To use an S3-compatible service such as MinIO, point the connector at its endpoint:

```yaml
env:
  DSXCONNECTOR_S3_ENDPOINT_URL: "https://minio.example.com"
  # Set to "false" only for lab endpoints with self-signed certificates.
  DSXCONNECTOR_S3_ENDPOINT_VERIFY: "true"
```

The credentials Secret holds the service's access key and secret key.

---

## Key Settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE` | Must be `"true"` for DSX-Connect 2 registration. |
| `env.DSXCONNECTOR_REGISTER_WITH_CORE` | `"false"` for DSX-Connect 2-only deployments. |
| `env.DSXCONNECTOR_DSX_CONNECT_URL` | DSX-Connect API URL. In-cluster default is `http://dsx-connect-api:8091`. |
| `env.DSXCONNECTOR_INSTANCE_ID` | Stable identity for this connector instance. Changing it creates a separate connector record. |
| `env.DSXCONNECTOR_NG_PLATFORM` | Connector type. Use `"s3"`. |
| `env.DSXCONNECTOR_NG_PLATFORM_KEY` | Stable key for the AWS account or boundary this connector represents. |
| `env.DSXCONNECTOR_ASSET` | Optional `bucket` or `bucket/prefix`. Restricts webhook events and provides the configured-asset discovery source. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude filter relative to `DSXCONNECTOR_ASSET`. |
| `env.DSXCONNECTOR_S3_ENDPOINT_URL` | Optional endpoint for S3-compatible storage. |
| `env.DSXCONNECTOR_S3_ENDPOINT_VERIFY` | TLS verification for the custom endpoint. Default `true`. |
| `secrets.name` | Secret with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Default `aws-credentials`. |
| `envSecretRefs` | Extra Secrets projected as environment variables, such as `AWS_SESSION_TOKEN` or `AWS_DEFAULT_REGION`. |
| `service.port` | Listen and Service port. Default `80`; use `8080` on OpenShift. |
| `replicaCount` | Connector pods. Extra replicas serve concurrent reads; they do not parallelize enumeration. |

## Legacy and Fallback Settings

`DSXCONNECTOR_ITEM_ACTION` (`nothing`, `delete`, `tag`, `move`, `move_tag`) and `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` are connector-level remediation defaults from DSX-Connect 1.x.
In DSX-Connect 2, protection profiles send the requested action with each remediation; the connector uses these values only when no action is requested.

---

## Verify Registration

```bash
kubectl get pods -n dsx-connect
kubectl logs -n dsx-connect deploy/s3-aws-s3-connector-chart
```

A healthy start logs `Registered connector with dsx-connect-ng control plane` followed by `Connector is READY`.

In the Operator Console, the connector appears under **Assets > Connectors**.
Under **Assets > Protected**, set the coverage filter to **All** or **Unprotected** to see discovered buckets, then protect the buckets you want scanned.

## Tear Down

```bash
helm uninstall s3 -n dsx-connect
```

## Common Issues

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Pod stuck in `CreateContainerConfigError` | The AWS credentials Secret or one of its keys is missing | `kubectl get secret aws-credentials -n dsx-connect -o jsonpath='{.data}' \| jq 'keys'` |
| Pod crash-loops with `permission denied` binding port 80 | Non-root runtime such as OpenShift | Set `service.port: 8080` |
| Connector starts but does not register | API URL is wrong or the API is unavailable | Check `DSXCONNECTOR_DSX_CONNECT_URL` and the API Service |
| Discovery shows `permission_denied` | Missing `s3:ListAllMyBuckets` | Grant it, or set `DSXCONNECTOR_ASSET` |
| Scans fail with `connector proxy transport failure` | Scan workers cannot reach the connector address stored on the integration | Compare the integration's `config.reader.proxy.endpoint_url` with the connector Service and port |
| Webhook events are ignored | `DSXCONNECTOR_ASSET`, its prefix, or `DSXCONNECTOR_FILTER` excludes the object | Connector logs show `Ignored by bucket mismatch`, `base prefix`, or `filter` |
| Connector appears offline | Heartbeats stopped or the lease expired | Check pod status and logs |

For failed scan items and dead letter queues, see [Failed Scans and Dead Letter Queues](../../../operations/dead-letter-queues.md).
