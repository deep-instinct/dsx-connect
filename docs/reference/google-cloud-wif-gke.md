# Google Cloud WIF for GCS Connector on GKE

Use this guide when deploying the Google Cloud Storage connector on GKE without a long-lived service account JSON key.
This is the recommended production credential path for GKE.

For local labs or non-GKE deployments, a mounted service account JSON key is still supported.
See [Google Cloud Credentials](google-cloud-credentials.md).

## What WIF Does

Workload Identity Federation for GKE lets a Kubernetes workload authenticate to Google Cloud APIs without mounting a static key file.
For the GCS connector, the Kubernetes service account used by the pod is allowed to impersonate a Google service account.
The Google client libraries then resolve credentials through Application Default Credentials.

WIF is only authentication.
The Google service account still needs IAM roles for the specific GCS, Pub/Sub, and Cloud Asset Inventory operations that DSX-Connect should perform.

## Variables

Set these values for the examples below:

```bash
export PROJECT_ID="example-gcs-project"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export CLUSTER_NAME="example-gke"
export CLUSTER_LOCATION="us-central1"
export NAMESPACE="dsx-connect"
export KSA_NAME="gcs-connector"
export GSA_NAME="dsx-gcs-connector"
export GSA_EMAIL="${GSA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Set one of these for broad bucket discovery.
export ASSET_INVENTORY_SCOPE="projects/${PROJECT_ID}"
# export ASSET_INVENTORY_SCOPE="folders/FOLDER_ID"
# export ASSET_INVENTORY_SCOPE="organizations/ORG_ID"
```

Where the values come from:

| Variable | Source |
| --- | --- |
| `PROJECT_ID` | The Google Cloud project used for the connector setup in these examples: API enablement, quota context, and the Google service account. For GKE deployments, this is also commonly the cluster project. It does not have to limit discovery to one project when `ASSET_INVENTORY_SCOPE` is set to a folder or organization. Find project IDs in the Google Cloud console project selector or with `gcloud projects list`. |
| `PROJECT_NUMBER` | The numeric project identifier for `PROJECT_ID`. The example derives it with `gcloud projects describe`; you normally do not choose this value. |
| `CLUSTER_NAME` | GKE only. The name of the existing GKE cluster where the connector pod will run. This is user-defined when the cluster is created. List clusters with `gcloud container clusters list --project "$PROJECT_ID"`. If deploying on OpenShift or another Kubernetes distribution, this value is not used by the GKE commands below. |
| `CLUSTER_LOCATION` | GKE only. The region or zone of the GKE cluster, such as `us-central1` or `us-central1-a`. Use the location shown by `gcloud container clusters list`. If deploying on OpenShift or another Kubernetes distribution, this value is not used by the GKE commands below. |
| `NAMESPACE` | The Kubernetes namespace where DSX-Connect and the connector are deployed. Use the namespace from your Helm install; these examples use `dsx-connect`. |
| `KSA_NAME` | The Kubernetes service account used by the GCS connector pod. This must match the service account configured in the connector Helm values. |
| `GSA_NAME` | The Google service account name to create or reuse for the connector. This is user-defined, but should be unique enough to identify the DSX GCS connector. |
| `GSA_EMAIL` | The service account email derived from `GSA_NAME` and `PROJECT_ID`. Google Cloud uses this identity for IAM grants and WIF impersonation. |
| `ASSET_INVENTORY_SCOPE` | The Cloud Asset Inventory parent to enumerate for bucket discovery. Use `projects/PROJECT_ID` for one project, `folders/FOLDER_ID` for all projects under a folder, or `organizations/ORG_ID` for organization-wide discovery. For folder or organization discovery, `PROJECT_ID` still identifies the connector's Google service account and GKE setup project; the inventory scope controls how broadly buckets are discovered. |

## Enable APIs

```bash
gcloud services enable \
  container.googleapis.com \
  iamcredentials.googleapis.com \
  cloudasset.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  --project "$PROJECT_ID"
```

## Enable WIF on Cluster

Choose the tab for the Kubernetes platform that will run the connector.

=== "GKE"

    Autopilot clusters have Workload Identity Federation for GKE enabled.
    For Standard clusters, enable it on the cluster and ensure the node pool uses the GKE metadata server:

    ```bash
    gcloud container clusters update "$CLUSTER_NAME" \
      --location "$CLUSTER_LOCATION" \
      --workload-pool="${PROJECT_ID}.svc.id.goog"

    gcloud container node-pools update NODEPOOL_NAME \
      --cluster "$CLUSTER_NAME" \
      --location "$CLUSTER_LOCATION" \
      --workload-metadata=GKE_METADATA
    ```

    Then get cluster credentials:

    ```bash
    gcloud container clusters get-credentials "$CLUSTER_NAME" \
      --location "$CLUSTER_LOCATION" \
      --project "$PROJECT_ID"
    ```

    The GKE flow uses the GKE metadata server and the `iam.gke.io/gcp-service-account` Kubernetes service account annotation.

=== "OpenShift"

    OpenShift does not use GKE-managed Workload Identity Federation or the GKE metadata server.
    Do not run the `gcloud container clusters ...` commands and do not use the GKE `iam.gke.io/gcp-service-account` annotation.

    For OpenShift, use one of these authentication paths:

    * Mount a Google service account JSON key as a Kubernetes Secret and set `gcp.credentialsSecretName` when deploying the connector.
    * For keyless authentication, configure Google IAM Workload Identity Federation for generic Kubernetes. That setup trusts the cluster's Kubernetes ServiceAccount token issuer, grants the federated principal access to impersonate the Google service account, mounts an external account credential configuration into the pod, and sets `GOOGLE_APPLICATION_CREDENTIALS` to that credential configuration file.

    The mounted service account key path is covered in [Google Cloud Credentials](google-cloud-credentials.md) and in the GCS connector deployment guide.

=== "k3s and Other Non-GKE"

    There is no direct k3s equivalent to the GKE commands above.
    Those commands enable GKE-managed Workload Identity Federation and the GKE metadata server.

    For a k3s lab, the supported DSX-Connect chart path is usually a mounted Google service account JSON key.
    Create a Kubernetes Secret that contains the key and set `gcp.credentialsSecretName` when deploying the connector.
    That path is covered in [Google Cloud Credentials](google-cloud-credentials.md) and in the GCS connector deployment guide.

    For keyless k3s or other self-managed Kubernetes deployments, use Google IAM Workload Identity Federation for generic Kubernetes instead of GKE WIF.
    That is a separate setup: configure a workload identity pool/provider that trusts the cluster's Kubernetes ServiceAccount token issuer, grant the federated principal access to impersonate the Google service account, mount the external account credential configuration into the pod, and set `GOOGLE_APPLICATION_CREDENTIALS` to that credential configuration file.
    Do not use the GKE `iam.gke.io/gcp-service-account` annotation for that flow.

## Create the Google Service Account

```bash
gcloud iam service-accounts create "$GSA_NAME" \
  --project "$PROJECT_ID" \
  --display-name "DSX GCS Connector"
```

## Grant DSX Connector Permissions

Grant only the roles needed for the deployment.
Discovery, object reads, monitoring, and remediation are intentionally separate.

### Cloud Asset Inventory Discovery

For project scope:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/cloudasset.viewer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/serviceusage.serviceUsageConsumer"
```

For folder or organization scope, grant `roles/cloudasset.viewer` at that scope instead.
Some environments also require `roles/serviceusage.serviceUsageConsumer` on the selected quota/billing project used by the caller.

### Object Reads

Grant read access where DSX-Connect should scan.
Bucket-level access is usually the safest default:

```bash
export BUCKET="example-bucket"

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/storage.objectViewer"
```

For broad project-level access, grant the same role on the project instead:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/storage.objectViewer"
```

### Remediation

If the connector will move, tag, or delete objects, grant write-capable object permissions only where remediation is allowed:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/storage.objectAdmin"
```

Detect-only deployments do not need `roles/storage.objectAdmin`.

### Pub/Sub Monitoring

If bucket monitoring is enabled, grant the connector access to consume the Pub/Sub subscription:

```bash
export SUBSCRIPTION="gcs-events-dsx-connector"

gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${GSA_EMAIL}" \
  --role "roles/pubsub.subscriber"
```

Bucket notifications and the Pub/Sub topic/subscription are covered in [Google Cloud Storage Bucket Notifications with Pub/Sub](google-cloud-pubsub.md).

## Bind the Kubernetes Service Account to the Google Service Account

The GCS connector Helm chart can create the Kubernetes service account.
Before deploying, allow that Kubernetes service account to impersonate the Google service account:

```bash
gcloud iam service-accounts add-iam-policy-binding "$GSA_EMAIL" \
  --project "$PROJECT_ID" \
  --role "roles/iam.workloadIdentityUser" \
  --member "serviceAccount:${PROJECT_ID}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]"
```

The Helm values must create or use the same Kubernetes service account and add the GKE annotation:

```yaml
serviceAccount:
  create: true
  name: gcs-connector
  annotations:
    iam.gke.io/gcp-service-account: dsx-gcs-connector@example-gcs-project.iam.gserviceaccount.com
  automountServiceAccountToken: true

gcp:
  credentialsSecretName: ""
```

`gcp.credentialsSecretName: ""` is important.
It keeps `GOOGLE_APPLICATION_CREDENTIALS` unset so the connector uses ADC/WIF instead of a mounted JSON key.

## Deploy the Connector

Set the chart version to deploy:

```bash
export GCS_VERSION="2.0.8"
```

`GCS_VERSION` is used by the Helm commands below to select the Google Cloud Storage connector chart version from OCI.
For released charts, the chart `appVersion` and default connector image tag should match this version unless you intentionally override the image tag.

Start from the chart example:

```bash
helm pull oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
  --version "$GCS_VERSION" \
  --untar

cp google-cloud-storage-connector-chart/examples/values-gke-wif.example.yaml \
  gcs-wif-values.yaml
```

Edit:

```yaml
env:
  DSXCONNECTOR_INSTANCE_ID: "gcs-prod-project-1"
  DSXCONNECTOR_NG_PLATFORM: "gcs"
  DSXCONNECTOR_NG_PLATFORM_KEY: "projects/example-gcs-project"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "projects/example-gcs-project"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
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

## Verify

Check that the rendered pod uses the intended Kubernetes service account:

```bash
kubectl get deploy gcs-google-cloud-storage-connector \
  -n "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.serviceAccountName}{"\n"}'
```

Confirm that no JSON credential env var is mounted:

```bash
kubectl get deploy gcs-google-cloud-storage-connector \
  -n "$NAMESPACE" \
  -o yaml | grep -E "GOOGLE_APPLICATION_CREDENTIALS|gcp-creds" || true
```

Expected result: no output.

Check connector logs:

```bash
kubectl logs -n "$NAMESPACE" deploy/gcs-google-cloud-storage-connector
```

Verify discovery from DSX-Connect or by calling the connector service in-cluster.
When `DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE` is set, the connector should use Cloud Asset Inventory for bucket discovery.

## Troubleshooting

`403 cloudasset.assets.listResource permission denied`:
The Google service account needs Cloud Asset Inventory permission at the configured project, folder, or organization scope.

`403 storage.objects.get` or `403 storage.objects.list`:
The Google service account needs object viewer permissions on the bucket or broader scope.

`403 pubsub.subscriptions.consume`:
The Google service account needs `roles/pubsub.subscriber` on the subscription.

The pod still expects `/app/creds/service-account.json`:
Set `gcp.credentialsSecretName: ""` and confirm no `GOOGLE_APPLICATION_CREDENTIALS` env var is rendered.

The connector uses the wrong Kubernetes service account:
Check `serviceAccount.name`, `serviceAccount.create`, and `spec.template.spec.serviceAccountName` in the rendered deployment.

## Official Google References

* [Authenticate to Google Cloud APIs from GKE workloads](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
* [Configure Workload Identity Federation with Kubernetes](https://cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes)
* [Cloud Asset Inventory roles and permissions](https://cloud.google.com/asset-inventory/docs/access-control)
* [Cloud Storage IAM roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
* [Pub/Sub access control](https://cloud.google.com/pubsub/docs/access-control)
