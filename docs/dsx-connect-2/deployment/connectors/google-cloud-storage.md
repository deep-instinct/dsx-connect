# Google Cloud Storage Connector - Helm Deployment

{% include-markdown "shared/connectors/google-cloud-storage/_intro.md" %}

---

## Prerequisites

Before deploying the connector you must configure Google Cloud credentials and IAM.

Recommended for production on GKE:

* Workload Identity Federation for GKE
* no mounted service account JSON key
* Cloud Asset Inventory scope for project, folder, or organization bucket discovery

See [Google Cloud WIF for GCS Connector on GKE](../../../reference/google-cloud-wif-gke.md).

Supported for local labs and transitional deployments:

* mounted service account JSON credential
* bucket-level or project-level object permissions

Required:

* permission to list and read objects

Optional, for remediation actions:

* permission to move or delete objects

See [Google Cloud Credentials](../../../reference/google-cloud-credentials.md) for the JSON-key path.

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

## Minimal JSON-Key Deployment

The following steps install the connector with minimal configuration changes for DSX-Connect 2 registration and optional Pub/Sub monitoring.

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
    This example enables Pub/Sub monitoring; set `DSXCONNECTOR_MONITOR=false` if you are doing scan-only testing before Pub/Sub is ready.

    ```bash
    export NAMESPACE=dsx-connect
    export GCS_VERSION=2.0.7

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
      --set-string env.DSXCONNECTOR_MONITOR=true \
      --set-string env.GCS_PUBSUB_PROJECT_ID=example-gcs-project \
      --set-string env.GCS_PUBSUB_SUBSCRIPTION=gcs-events-dsx-connector \
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

    Copy the DSX-Connect 2 lab example values file and edit it for the connector identity, GCP credentials, and target bucket:

    ```bash
    cp google-cloud-storage-connector-chart/examples/values-lab.example.yaml \
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
      DSXCONNECTOR_MONITOR: "true"
      GCS_PUBSUB_PROJECT_ID: "example-gcs-project"
      GCS_PUBSUB_SUBSCRIPTION: "gcs-events-dsx-connector"

    gcp:
      credentialsSecretName: "gcp-sa"
      mountPath: "/app/creds"
      filename: "service-account.json"
    ```

    `GCS_PUBSUB_PROJECT_ID` is the Google Cloud project that owns the Pub/Sub subscription.
    `GCS_PUBSUB_SUBSCRIPTION` is the operator-created Google Cloud Pub/Sub subscription that receives bucket event messages.
    The connector accepts either the subscription name or the full subscription path.

    `DSXCONNECTOR_ASSET` and `DSXCONNECTOR_FILTER` are intentionally omitted from the DSX-Connect 2 values above.
    Normal asset protection comes from discovered assets and protected scopes in the control plane.
    Set `DSXCONNECTOR_ASSET` only when you want a configured single-bucket fallback for labs, repo checks, or the `configured_asset` discovery source.

    `DSXCONNECTOR_ITEM_ACTION` and `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` are legacy/default connector remediation settings.
    DSX-Connect 2 protection profiles send the requested remediation action at runtime.
    Only set these values when you need DSX-Connect 1.x behavior or an explicit connector-side fallback:

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

## GKE WIF Deployment

For production GKE deployments, prefer Workload Identity Federation instead of a mounted service account JSON key.
Complete the GCP setup in [Google Cloud WIF for GCS Connector on GKE](../../../reference/google-cloud-wif-gke.md), then deploy with the chart's WIF values example.

```bash
export NAMESPACE=dsx-connect
export GCS_VERSION=2.0.7

helm pull oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version "$GCS_VERSION" \
  --untar

cp google-cloud-storage-connector-chart/examples/values-gke-wif.example.yaml \
  gcs-wif-values.yaml
```

Edit the values for your project, Google service account, DSX-Connect URL, and Cloud Asset Inventory scope:

```yaml
env:
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "gcs-prod-project-1"
  DSXCONNECTOR_NG_PLATFORM: "gcs"
  DSXCONNECTOR_NG_PLATFORM_KEY: "projects/example-gcs-project"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "projects/example-gcs-project"

serviceAccount:
  create: true
  name: "gcs-connector"
  annotations:
    iam.gke.io/gcp-service-account: "dsx-gcs-connector@example-gcs-project.iam.gserviceaccount.com"
  automountServiceAccountToken: true

gcp:
  credentialsSecretName: ""
```

Install:

```bash
helm upgrade --install gcs \
  oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version "$GCS_VERSION" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  -f gcs-wif-values.yaml
```

With `gcp.credentialsSecretName: ""`, the chart does not mount `/app/creds` and does not set `GOOGLE_APPLICATION_CREDENTIALS`.
The Google SDK resolves credentials through GKE Workload Identity Federation.

---

## Platform Identity and Repository Scope

The GCS connector has two related but separate concepts:

* `DSXCONNECTOR_NG_PLATFORM` identifies the connector adapter type. For this connector, use `gcs`.
* `DSXCONNECTOR_NG_PLATFORM_KEY` is a stable, operator-chosen key used by DSX-Connect 2 to group and display the platform boundary represented by this connector.
* Protected scopes in DSX-Connect 2 identify the GCS buckets or prefixes to protect.
* `DSXCONNECTOR_ASSET` is an optional configured bucket or bucket/prefix fallback, primarily useful for single-bucket labs, repo checks, and the `configured_asset` discovery source.

`DSXCONNECTOR_NG_PLATFORM_KEY` may be the real GCP project ID if the connector represents a project.
It could also be a folder, organization, tenant, account label, lab name, or other stable boundary that makes sense operationally.
It is not automatically read from the service-account JSON and does not grant GCS access.
Actual bucket access comes from the mounted Google Cloud credential and IAM permissions.

## Key Settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE` | Must be `"true"` for DSX-Connect 2 registration. |
| `env.DSXCONNECTOR_REGISTER_WITH_CORE` | Usually `"false"` for DSX-Connect 2-only deployments. |
| `env.DSXCONNECTOR_DSX_CONNECT_NG_URL` | DSX-Connect 2 API URL. In-cluster default is `http://dsx-connect-api:8091`. |
| `env.DSXCONNECTOR_INSTANCE_ID` | Stable identity for this running connector instance. Changing it creates a separate connector record. |
| `env.DSXCONNECTOR_NG_PLATFORM` | Connector adapter type. Use `"gcs"`. |
| `env.DSXCONNECTOR_NG_PLATFORM_KEY` | Stable operator-chosen key for the platform boundary shown and routed by DSX-Connect 2. It may match a GCP project, folder, org, tenant, or lab/account label, but it is not the credential source. |
| `env.DSXCONNECTOR_ASSET` | Optional configured bucket or `bucket/prefix` fallback. In DSX-Connect 2, protected scopes usually provide the actual scan target. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude list relative to `DSXCONNECTOR_ASSET` when the configured-asset path is used. |
| `env.DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE` | Optional Cloud Asset Inventory scope for broad bucket discovery, such as `projects/PROJECT_ID`, `folders/FOLDER_ID`, or `organizations/ORG_ID`. |
| `serviceAccount.create` | Creates a Kubernetes service account for WIF deployments when `true`. |
| `serviceAccount.annotations` | Kubernetes service account annotations, including `iam.gke.io/gcp-service-account` for GKE WIF. |
| `gcp.credentialsSecretName` | Secret name containing `service-account.json`. Leave empty for WIF/ADC. |

## Legacy and Fallback Settings

`DSXCONNECTOR_ITEM_ACTION` and `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` are connector-level remediation defaults.
They are the primary remediation controls for DSX-Connect 1.x/core flows.

For DSX-Connect 2, protection profiles generate a requested action for each remediation event.
The connector uses these env vars only as fallback defaults when no requested action is present.

## Monitoring Settings

Monitoring enables event-driven protection when objects are created or modified in Google Cloud Storage.

First, configure Google Cloud bucket notifications and Pub/Sub.
See [Google Cloud Storage Bucket Notifications with Pub/Sub](../../../reference/google-cloud-pubsub.md).

Then configure the connector with the Pub/Sub settings from that setup:


```yaml
env:
  DSXCONNECTOR_MONITOR: "true"
  GCS_PUBSUB_PROJECT_ID: "example-gcs-project"
  GCS_PUBSUB_SUBSCRIPTION: "gcs-events-dsx-connector"
```

Important distinctions:

* `env.GCS_PUBSUB_PROJECT_ID` is the Google Cloud project ID that owns the Pub/Sub subscription. Do not use the numeric project number here.
* `env.GCS_PUBSUB_SUBSCRIPTION` is the operator-created Google Cloud Pub/Sub subscription that receives bucket event messages.
* `env.GCS_PUBSUB_SUBSCRIPTION` can be either the subscription name, such as `gcs-events-dsx-connector`, or the full path, such as `projects/example-gcs-project/subscriptions/gcs-events-dsx-connector`.
* The subscription must be attached to the same topic used by the bucket notifications.
* In native Pub/Sub mode, the connector consumes the subscription directly using Google's client SDK. It does not use `/webhook/event`.

### Which Buckets Are Monitored?

Google Cloud determines which buckets publish object events.
Add bucket notifications in Google Cloud for each bucket that should emit events to the Pub/Sub topic.

DSX-Connect 2 determines whether those events result in protection work.
A connector may receive events for any bucket wired to the subscription, but scanning/remediation should only be queued for buckets with protection enabled in DSX-Connect 2.

In short:

* configure bucket notifications in Google Cloud for buckets that should publish events
* configure the connector to consume the Pub/Sub subscription
* enable protection in DSX-Connect 2 for buckets that should be acted on

## Verify Registration

Check the connector pod:

```bash
kubectl get pods -n dsx-connect
kubectl logs -n dsx-connect deploy/gcs-google-cloud-storage-connector
```

Open the Operator Console:

```text
http://127.0.0.1:8091/
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
