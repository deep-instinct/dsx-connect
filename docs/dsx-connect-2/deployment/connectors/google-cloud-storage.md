# Google Cloud Storage Connector - Helm Deployment

{% include-markdown "shared/connectors/google-cloud-storage/_intro.md" %}

---

## Prerequisites

Before deploying the connector you must create a Google Cloud service account with access to the target bucket.

Required:

* a service account JSON credential
* permission to list and read objects

Optional, for remediation actions:

* permission to move or delete objects

See [Google Cloud Credentials](../../../reference/google-cloud-credentials.md).

---

## Full Scan and Monitoring Guidance

Full scans establish baseline coverage across a bucket or prefix at a point in operational time.

Because object storage remains active during scanning, full scans should be treated as best-effort enumeration of a live data set rather than immutable point-in-time snapshots.

Continuous monitoring or event-driven protection maintains convergence by detecting:

* newly created objects
* modified objects
* overwritten objects
* post-scan changes

Operationally:

* full scans are recommended during lower repository activity when possible
* monitoring should remain enabled for steady-state protection
* protection coverage is achieved through the combination of baseline scanning and continuous monitoring

---

## Minimal Deployment

The following steps install the connector with minimal configuration changes, supporting full-scan only.

### Create the GCP service-account Secret

The GCS connector needs a Kubernetes Secret containing the service account JSON.
The examples below use a secret named `gcp-sa` with a key named `service-account.json`.

```bash
export NAMESPACE=dsx-connect

kubectl create namespace "$NAMESPACE"

kubectl create secret generic gcp-sa \
  --namespace "$NAMESPACE" \
  --from-file=service-account.json=/path/to/gcp-sa.json
```

If the namespace may already exist, use an apply-style manifest:

```bash
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
```

### Deploy

=== "Quick Install"

    Minimal install using Helm CLI overrides.

    ```bash
    export NAMESPACE=dsx-connect
    export GCS_VERSION=2.0.2

    helm upgrade --install gcs \
      oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
      --version "$GCS_VERSION" \
      --namespace "$NAMESPACE" \
      --create-namespace \
      --set-string env.DSXCONNECTOR_REGISTER_WITH_CORE=false \
      --set-string env.DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true \
      --set-string env.DSXCONNECTOR_DSX_CONNECT_URL=http://dsx-connect-api:8091 \
      --set-string env.DSXCONNECTOR_DSX_CONNECT_NG_URL=http://dsx-connect-api:8091 \
      --set-string env.DSXCONNECTOR_INSTANCE_ID=gcs-local-1 \
      --set-string env.DSXCONNECTOR_NG_PLATFORM=gcs \
      --set-string env.DSXCONNECTOR_NG_PLATFORM_KEY=demo-project \
      --set-string env.DSXCONNECTOR_ASSET=lg-test-01 \
      --set-string env.DSXCONNECTOR_FILTER="" \
      --set-string env.DSXCONNECTOR_ITEM_ACTION=nothing \
      --set gcp.credentialsSecretName=gcp-sa
    ```

    !!! note "--version"
        The version number is the chart version; removing it installs the latest chart version.

=== "values.yaml Install"

    Use a values file when deploying in production or GitOps workflows.

    First, pull the chart:

    ```bash
    helm pull oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
      --version <connector_version> \
      --untar
    ```

    Copy the DSX-Connect 2 example values file and edit it for the target project and bucket:

    ```bash
    cp docs/dsx-connect-2/deployment/examples/gcs-connector-values.yaml \
      gcs-connector-values.yaml
    ```

    Relevant DSX-Connect 2 values:

    ```yaml
    env:
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
      DSXCONNECTOR_MONITOR: "false"
      GCS_PUBSUB_PROJECT_ID: ""
      GCS_PUBSUB_SUBSCRIPTION: ""

    gcp:
      credentialsSecretName: "gcp-sa"
      mountPath: "/app/creds"
      filename: "service-account.json"
    ```

    If you use `DSXCONNECTOR_ITEM_ACTION=move`, also configure where objects should be moved:

    ```yaml
    env:
      DSXCONNECTOR_ITEM_ACTION: "move"
      DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "dsxconnect-quarantine"
    ```

    Install the released chart:

    ```bash
    helm upgrade --install gcs \
      oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
      --version "$GCS_VERSION" \
      --namespace "$NAMESPACE" \
      --create-namespace \
      -f gcs-connector-values.yaml
    ```

---

## Required Settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE` | Must be `"true"` for DSX-Connect 2 registration. |
| `env.DSXCONNECTOR_REGISTER_WITH_CORE` | Usually `"false"` for DSX-Connect 2-only deployments. |
| `env.DSXCONNECTOR_DSX_CONNECT_NG_URL` | DSX-Connect 2 API URL. In-cluster default is `http://dsx-connect-api:8091`. |
| `env.DSXCONNECTOR_INSTANCE_ID` | Stable connector instance ID. |
| `env.DSXCONNECTOR_NG_PLATFORM` | Use `"gcs"`. |
| `env.DSXCONNECTOR_NG_PLATFORM_KEY` | GCP project, tenant, or other boundary represented by this connector. |
| `env.DSXCONNECTOR_ASSET` | Bucket or `bucket/prefix` root to scan. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude list relative to the asset root. |
| `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Connector-level remediation defaults. Protection profiles in DSX-Connect 2 decide which action is requested. |
| `gcp.credentialsSecretName` | Secret name containing `service-account.json`. |

## Monitoring Settings

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

Notes:

* Pub/Sub is the recommended trigger path.
* `env.GCS_PUBSUB_PROJECT_ID` should be the project ID, not the numeric project number.
* `env.GCS_PUBSUB_SUBSCRIPTION` can be either the subscription name or full subscription path.
* The subscription must be attached to the same topic used by the bucket notification.
* In native Pub/Sub mode, the connector consumes the subscription directly using Google's client SDK. It does not use `/webhook/event`.

## Verify Registration

Check the connector pod:

```bash
kubectl get pods -n dsx-connect
kubectl logs -n dsx-connect deploy/gcs-google-cloud-storage-connector
```

Open the Operator Console:

```text
http://127.0.0.1:8091/api/v1/ui/
```

The connector should appear under **Assets > Connectors**.
When the connector stops heartbeating, the console shows it as offline after its lease expires.

## Tear Down

```bash
helm uninstall gcs -n dsx-connect
```

## Common Issues

| Symptom | Likely cause | Check |
| --- | --- | --- |
| Connector pod is `ImagePullBackOff` | Cluster cannot pull the image | Verify registry, tag, pull secret, and `image.pullPolicy` |
| GCS pod has `FailedMount` | Secret name or namespace is wrong | `kubectl get secret gcp-sa -n dsx-connect` |
| Connector starts but does not register | Control plane URL is wrong or API is unavailable | Check `DSXCONNECTOR_DSX_CONNECT_NG_URL` and API service |
| Connector registers but asset reads fail | Repository credentials or asset settings are wrong | Check connector logs and repository-specific secret values |
| Connector appears offline | Heartbeats stopped or lease expired | Check connector pod status and logs |
