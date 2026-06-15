# Connector Deployment (Docker Compose)

This page describes how connectors are deployed with Docker Compose and links to each connector’s Compose-specific guide.

## How it works

* Each connector is run as a separate service (container) on the same Docker host as DSX-Connect Core.
* Connectors join the same Docker network as the Core API so they can register and receive scan requests.
* Configuration is done via environment variables, typically in a `.env` file used with the connector’s Compose file.
* Credentials (service accounts, secrets) are usually mounted as files or passed via env (e.g. `GOOGLE_APPLICATION_CREDENTIALS`, Azure connection strings). See [Reference → Repository Credentials](../../reference/azure-credentials.md) and the connector-specific pages below.
* Connector Compose files and sample env files are included in the [Docker Compose bundles](https://github.com/deep-instinct/dsx-connect/releases) (per-connector subfolders).

### Environment mode for connectors

Set connector environment mode explicitly:

```env
DSXCONNECTOR_APP_ENV=prod
```

Accepted fallback:

```env
APP_ENV=prod
```

Why:

* In `stg`/`prod`, connector startup logs mask identifier fields (for example tenant/client IDs).
* In `dev`, identifier logs are left unmasked to simplify troubleshooting.

For core deployment and resource guidance, see [Core Deployment (Docker Compose)](dsx-connect.md) and [Resource Recommendations](resource-recommendations.md). For bind mounts and storage (e.g. filesystem connector, NFS/SMB), see [Storage & Mounts](storage-mounts.md).

## Connector guides (Docker Compose)

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
