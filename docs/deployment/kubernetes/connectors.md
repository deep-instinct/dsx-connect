# Connector Deployment (Kubernetes / Helm)

This page describes how connectors are deployed with Helm and links to each connector’s Kubernetes-specific guide.

## How it works

* Each connector is deployed via its own Helm chart (e.g. `google-cloud-storage-connector-chart`) from the same OCI registry as the Core chart.
* Connectors run in the same cluster (and typically the same namespace) as DSX-Connect Core and use in-cluster service DNS (e.g. `http://dsx-connect-api`) to reach the API.
* Configuration is done via Helm values (`env.*`, `workers`, `replicaCount`, etc.). Secrets are stored as Kubernetes Secrets and referenced in the chart.
* For credentials and permissions, see [Reference → Repository Credentials](../../reference/azure-credentials.md) and the connector-specific pages below. For secret best practices, see [Core Deployment](dsx-connect.md) and [Configure Authentication](authentication.md).

### Environment mode for connectors

Set connector environment mode in chart values:

```yaml
env:
  DSXCONNECTOR_APP_ENV: prod
```

Accepted fallback (if explicit key is not set):

```yaml
env:
  APP_ENV: prod
```

Why:

* In `stg`/`prod`, connector startup logs mask identifier fields (for example tenant/client IDs).
* In `dev`, identifier logs are left unmasked to simplify troubleshooting.

For core deployment and scaling, see [Core Deployment (Helm)](dsx-connect.md), [Resource Recommendations](resource-recommendations.md), and [Scaling & Performance](scaling.md).

## Connector guides (Kubernetes / Helm)

| Connector | Guide |
| --------- | ----- |
| **Filesystem** | [Filesystem](filesystem.md) |
| **Google Cloud Storage** | [Google Cloud Storage](google-cloud-storage.md) |
| **SharePoint** | [SharePoint](sharepoint.md) |
| **OneDrive** | [OneDrive](onedrive.md) |
| **M365 Mail** | [M365 Mail](m365-mail.md) |
| **Salesforce** | [Salesforce](salesforce.md) |
| **AWS S3** *(reference architecture)* | [AWS S3](aws-s3.md) |
| **Azure Blob Storage** *(reference architecture)* | [Azure Blob Storage](azure-blob.md) |

To choose a connector by use case, see [Choose your connector](../../connectors/index.md).
