# Google Cloud Storage Connector

The **Google Cloud Storage connector** scans objects stored in a Google Cloud Storage bucket.

It supports:

- full bucket scans
- continuous monitoring (on-access scanning)
- remediation actions (delete, move, tag)

The connector can monitor bucket changes using **Google Cloud Pub/Sub notifications**.

Alternatively, events can be forwarded using middleware (Cloud Run / Cloud Functions) via the connector webhook API.

---

## When to Use This Connector

Use the Google Cloud Storage connector when scanning:

- Google Cloud Storage buckets
- bucket prefixes
- object uploads in real time

Typical use cases include:

- malware scanning for uploaded files
- scanning data ingestion pipelines
- monitoring shared cloud storage

---

## Monitoring Options

The connector supports two monitoring approaches:

| Method | Description |
|---|---|
| Pub/Sub (recommended) | Direct bucket event notifications |
| Webhook events | Middleware triggers the connector |

Pub/Sub notifications are the recommended approach because they require minimal infrastructure.

---

## Assets

`DSXCONNECTOR_ASSET` defines the bucket or bucket prefix to scan.

Examples:
my-bucket
my-bucket/images


---

## Deployment Options

=== "Docker Compose"

    Deploy the connector locally using Docker.

    ➜ [Docker Deployment](../../deployment/docker/google-cloud-storage.md)

=== "Kubernetes (Helm)"

    Deploy the connector in a Kubernetes cluster using Helm.

    ➜ [Kubernetes Deployment](../../deployment/kubernetes/google-cloud-storage.md)