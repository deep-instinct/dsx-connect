# Docker Compose Deployment Overview

Use this page as the single checklist before diving into the connector-specific guides. It covers host requirements, where to obtain the Compose bundles, and the high-level workflow shared by every DSX-Connect Docker deployment.

Docker Compose is the fastest way to run the full platform on a single host.

---

## Prerequisites

* Docker Engine 20.10+
* Docker Compose v2 (`docker compose`)
* A Linux host, macOS Docker Desktop, or Windows Docker Desktop
* Network access to the DSXA scanner image repository
* Connector-specific credentials (for example: AWS IAM keys, Azure AD app secrets, GCP service-account JSON)

For environment settings and worker retry policies see:

➡️ [Deployment Advanced Settings](../advanced.md)

---

## Environment Configuration

Docker deployments typically use `.env` files to supply connector configuration and credentials.

Example:

```env
DSXCONNECTOR_ASSET=/mnt/data
DSXCONNECTOR_ITEM_ACTION=move
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine
```

These variables are injected into containers through the Compose file or inclusion on the command line using `--env-file.

Example:

```yaml
docker compose up --env-file sample.filesystem.env
```

Recommendations:

* Keep `.env` files **out of source control**
* Store secrets securely on the host system
* Use different `.env` files per connector instance

Unlike Kubernetes, Docker Compose does **not provide native secret management**, so operational environments should consider external secret tooling.

---

## Compose Bundles

The DSX-Connect project provides reference Compose bundles for:

* dsx-connect core
* connectors
* example deployments

Bundles are available in the GitHub release artifacts:

➡️ [https://github.com/deep-instinct/dsx-connect/releases](https://github.com/deep-instinct/dsx-connect/releases)

Each connector deployment guide references the specific Compose file used.

Example components include:

| Component                      | Compose service                   |
| ------------------------------ | --------------------------------- |
| dsx-connect core               | `dsx-connect-api`, workers, Redis |
| Filesystem connector           | `filesystem-connector`            |
| Google Cloud Storage connector | `gcs-connector`                   |
| SharePoint connector           | `sharepoint-connector`            |

These services communicate using the shared Docker network defined in the Compose project.

---

## Deployment Flow

1️⃣ **Prepare environment files**

Create `.env` files containing connector configuration and credentials.

Each connector guide provides a sample.

---

2️⃣ **Start DSX-Connect Core**

Follow:

➡️ [DSX-Connect Core Deployment](dsx-connect.md)

This launches:

* API service
* worker containers
* Redis
* optional syslog collector

Verify the API is reachable and the UI loads.

---

3️⃣ **Start connectors**

Choose the connector deployment guide under this section:

* Filesystem
* AWS S3
* Azure Blob Storage
* Google Cloud Storage
* SharePoint
* OneDrive
* M365 Mail
* Salesforce

Each connector runs as a separate container and registers with the DSX-Connect API.

---

4️⃣ **Networking and exposure**

Expose the DSX-Connect UI/API using:

* host port mapping
* reverse proxy (NGINX / Traefik)
* optional TLS termination

Connector webhook endpoints should only be exposed where required.

---

5️⃣ **Monitoring and lifecycle**

Common operational tasks include:

* reviewing container logs
* restarting connectors
* rotating connector credentials
* updating environment variables
* redeploying containers after configuration changes

Logs can be exported to external collectors via the syslog service.

---

## Scaling Considerations

Docker Compose runs on a **single host**.

Throughput tuning is primarily achieved through worker concurrency:

```
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY
```

You may also scale worker containers manually:

```bash
docker compose up --scale scan-request-worker=3
```

However Compose does not provide:

* multi-node orchestration
* autoscaling
* cluster-level scheduling
* high-availability Redis
* Kubernetes-style resource management

For large-scale or production environments, consider the Kubernetes deployment model.

---

## Next Steps

* Deploy DSX-Connect Core via [Core Deployment](dsx-connect.md)
* Choose the connector page that matches your repository
* Configure authentication and TLS if required
* Run your first scan and verify results through the DSX-Connect UI

Once the platform and at least one connector are running, you can monitor scans, adjust concurrency, and experiment with throughput before moving to Kubernetes for production-scale workloads.

