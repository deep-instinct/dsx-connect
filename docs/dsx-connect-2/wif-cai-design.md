# WIF and Cloud Asset Inventory Design

This page describes the target design for Google Cloud Workload Identity Federation and Cloud Asset Inventory support in DSX-Connect 2.
It is an implementation plan, not a statement that every item is already implemented.

The goal is to let a GCS connector represent a broad Google Cloud boundary, such as a project, folder, or organization, without relying on long-lived service account JSON keys.
The connector should be able to discover buckets through Cloud Asset Inventory, register those assets with DSX-Connect 2, and then read, monitor, scan, and remediate only where the deployed identity has the required permissions.

## Why This Matters

DSX-Connect 2 treats connectors as platform integrations, not only as single repository endpoints.
For GCS, that means one connector may represent:

* a single bucket
* a Google Cloud project
* a folder
* an organization

This makes deployment easier for large environments.
Instead of deploying a connector for every bucket, operations can deploy a connector for the Google Cloud boundary they own, discover buckets below it, and enable protection in bulk or selectively through the UI and API.

WIF and CAI are the two Google Cloud capabilities that make this production-friendly:

* **Workload Identity Federation** removes the need to mount a static `gcp-sa.json` file into the connector pod.
* **Cloud Asset Inventory** gives the connector a scalable way to discover buckets across a project, folder, or organization.

## Key Concepts

### WIF Is Authentication

Workload Identity Federation answers the question: who is this workload?

For a Kubernetes deployment, the connector pod runs as a Kubernetes service account.
Google Cloud maps that Kubernetes identity to a Google service account.
The connector then uses Application Default Credentials from the runtime environment instead of a mounted key file.

This gives us a cleaner production deployment model:

* no long-lived JSON key in a Kubernetes Secret
* no secret rotation burden for connector credentials
* identity is tied to the cluster workload
* IAM permissions stay in Google Cloud IAM

WIF does not grant repository access by itself.
The mapped Google service account still needs IAM roles for discovery, object reads, Pub/Sub monitoring, and remediation.

### CAI Is Discovery

Cloud Asset Inventory answers the question: what assets exist under this Google Cloud boundary?

For DSX-Connect 2, CAI should be used when the connector is deployed with a broad scope:

```text
organizations/1234567890
folders/1234567890
projects/my-project
```

The connector can use CAI to discover GCS buckets under that boundary and expose them as protectable assets in the Operator Console.

Discovery does not imply object access.
A connector may be able to see that a bucket exists, but still be unable to read or remediate objects in that bucket unless the connector service account has the required Storage IAM permissions.

## Target Deployment Model

The production GCS connector deployment should look like this:

1. A Google service account is created for the connector.
2. The connector service account receives CAI permissions at the project, folder, or organization scope.
3. The connector service account receives Storage and Pub/Sub permissions only where DSX-Connect should operate.
4. The Kubernetes service account is mapped to the Google service account using WIF.
5. The GCS connector Helm chart sets `serviceAccountName` and service account annotations.
6. The connector runs without `GOOGLE_APPLICATION_CREDENTIALS`.
7. The connector registers with DSX-Connect 2 and advertises discovery, monitoring, read, and remediation capabilities based on configuration and runtime checks.

The lab and local path can continue to support mounted JSON credentials for convenience.
The production path should prefer WIF.

## Proposed Helm Values

The GCS connector Helm chart should grow first-class service account support:

```yaml
serviceAccount:
  create: true
  name: gcs-connector
  annotations:
    iam.gke.io/gcp-service-account: dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com
  automountServiceAccountToken: true
```

The deployment should set:

```yaml
spec:
  serviceAccountName: gcs-connector
```

When WIF is used, the GCP credential secret should be disabled:

```yaml
gcp:
  credentialsSecretName: ""
```

The connector should then rely on Application Default Credentials provided by the runtime.
For local or non-WIF deployments, the existing secret-mounted JSON path can remain supported.

## Connector Configuration

The connector should support a broad inventory scope:

```yaml
env:
  DSXCONNECTOR_NG_PLATFORM: "gcs"
  DSXCONNECTOR_NG_PLATFORM_KEY: "organizations/1234567890"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "organizations/1234567890"
```

The platform key should identify the Google Cloud boundary represented by the connector.
For project-level deployments, use the project identifier.
For folder or organization deployments, use the folder or organization resource name.

Examples:

```yaml
env:
  DSXCONNECTOR_NG_PLATFORM_KEY: "projects/example-gcs-project"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "projects/example-gcs-project"
```

```yaml
env:
  DSXCONNECTOR_NG_PLATFORM_KEY: "folders/1234567890"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "folders/1234567890"
```

```yaml
env:
  DSXCONNECTOR_NG_PLATFORM_KEY: "organizations/1234567890"
  DSXCONNECTOR_GCS_ASSET_INVENTORY_SCOPE: "organizations/1234567890"
```

## IAM Model

Use separate IAM grants for discovery, object access, monitoring, and remediation.
This keeps broad visibility from becoming broad write access by accident.

### Discovery

Grant the connector Google service account Cloud Asset Inventory visibility at the project, folder, or organization scope:

```bash
gcloud organizations add-iam-policy-binding ORG_ID \
  --member "serviceAccount:dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/cloudasset.viewer"
```

For folder or project scope, apply the same role at that level instead.

Some environments may also require Service Usage access when calling Google APIs from the selected project:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member "serviceAccount:dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/serviceusage.serviceUsageConsumer"
```

### Object Reads

For scanning, grant object read access where protection is allowed:

```bash
gcloud storage buckets add-iam-policy-binding "gs://BUCKET" \
  --member "serviceAccount:dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/storage.objectViewer"
```

This can be applied narrowly per bucket, or more broadly at the project, folder, or organization level when that is acceptable.

### Monitoring

For Pub/Sub monitoring, grant subscriber access to the connector service account:

```bash
gcloud pubsub subscriptions add-iam-policy-binding SUBSCRIPTION \
  --project PROJECT_ID \
  --member "serviceAccount:dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/pubsub.subscriber"
```

Cloud Storage also needs permission to publish bucket notifications to the Pub/Sub topic:

```bash
gcloud pubsub topics add-iam-policy-binding TOPIC \
  --project PROJECT_ID \
  --member "serviceAccount:service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com" \
  --role "roles/pubsub.publisher"
```

### Remediation

For quarantine or delete remediation, the connector needs write-capable Storage permissions.
Use the narrowest practical scope:

```bash
gcloud storage buckets add-iam-policy-binding "gs://BUCKET" \
  --member "serviceAccount:dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com" \
  --role "roles/storage.objectAdmin"
```

Detect-only deployments should not need object write permissions.

## WIF on GKE

For GKE, the intended Kubernetes shape is:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gcs-connector
  namespace: dsx-connect
  annotations:
    iam.gke.io/gcp-service-account: dsx-gcs-connector@PROJECT_ID.iam.gserviceaccount.com
```

The connector pod uses that Kubernetes service account.
Google Cloud then exchanges the Kubernetes workload identity for credentials for the mapped Google service account.

The implementation should follow the official Google guidance:

* [Workload Identity Federation for GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
* [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation)
* [Workload Identity Federation with Kubernetes](https://cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes)

Non-GKE Kubernetes clusters can also use Workload Identity Federation, but the setup is more involved.
That should be treated as a later deployment path after the GKE path is clean.

## Runtime Behavior

At startup, the connector should:

1. Resolve credentials through Application Default Credentials.
2. Detect whether it is using a mounted key file, WIF, or another ADC source when possible.
3. Register with DSX-Connect 2.
4. Advertise configured capabilities.
5. Run lightweight permission checks for discovery, read, monitor, and remediation when possible.
6. Surface permission failures as connector health details rather than generic asset failures.

The Operator Console should make these states clear:

* discovery configured but CAI permission missing
* bucket discovered but object read permission missing
* monitoring configured but Pub/Sub subscription permission missing
* remediation configured but object write permission missing
* connector running with JSON credentials instead of WIF

This is important for broad deployments.
Operators need to know whether a bucket is unprotected because of policy, permission, scope, or connector health.

## Protection Workflow

With CAI discovery, a GCS connector can expose many buckets.
DSX-Connect 2 should support both bulk and granular protection:

* apply a default protection profile to newly protected buckets
* protect all discovered buckets under a connector
* protect buckets matching a filter
* change a bucket from one protection profile to another
* disable protection on selected buckets
* keep connector default profile changes from rewriting existing protected assets

The connector owns repository-specific access.
DSX-Connect owns the protection decision and records which profile applies to each protected asset.

## Implementation Phases

### Phase 1: Helm Service Account Support

Add service account support to the GCS connector chart:

* `serviceAccount.create`
* `serviceAccount.name`
* `serviceAccount.annotations`
* `serviceAccount.automountServiceAccountToken`
* `templates/serviceaccount.yaml`
* `spec.serviceAccountName` in the deployment

Keep the existing `gcp.credentialsSecretName` path for local and lab deployments.
When `credentialsSecretName` is empty, do not mount `/app/creds` and do not set `GOOGLE_APPLICATION_CREDENTIALS`.

### Phase 2: GKE WIF Documentation and Validation

Document a full GKE WIF deployment:

* create Google service account
* bind Kubernetes service account to Google service account
* configure Helm values
* verify ADC inside the pod
* verify connector registration
* verify bucket discovery and scan reads

### Phase 3: CAI Discovery Hardening

Make project, folder, and organization discovery explicit:

* normalize supported scope strings
* return discovered bucket identity, display name, project, location, and labels when available
* support pagination for large inventories
* distinguish configured asset discovery from CAI inventory discovery
* expose permission failures clearly

### Phase 4: Permission and Capability Status

Add connector status details for:

* authentication mode
* CAI discovery permission
* bucket read permission
* Pub/Sub subscription permission
* remediation permission
* last successful inventory sync
* last monitoring event received

These details should flow into the Operator Console.

### Phase 5: Non-GKE WIF

Evaluate non-GKE Kubernetes WIF after the GKE path is stable.
This may be useful for lab, k3s, or customer-managed Kubernetes, but it should not block the first production WIF design.

## Current Gaps

The current GCS connector deployment still expects service account JSON credentials for local Helm examples.
The chart does not yet provide first-class Kubernetes service account configuration for WIF annotations.

The connector can represent broader GCS boundaries conceptually, but CAI-backed organization and folder discovery needs to be hardened, documented, and surfaced cleanly in the UI.

The Operator Console should also grow better status for permission-specific failures.
For broad connector deployments, a generic failure is not enough; operators need to know whether the problem is discovery, read access, monitoring, remediation, or DSX-Connect reachability.

## Design Principles

Use WIF for production.
Use JSON keys only for local development, lab testing, or transitional deployments.

Keep discovery and object access separate.
A connector may discover broadly but read or remediate narrowly.

Make IAM failures visible.
Permission problems should show up as actionable connector or asset status, not only as logs.

Prefer one connector per operational boundary.
Use project, folder, or organization connectors where that matches how the customer operates.
Use single-bucket connectors only when that is the right isolation boundary.

Keep protection decisions in DSX-Connect.
The connector should normalize repository access and events.
DSX-Connect should decide which assets are protected and which protection profile applies.
