# Google Cloud Storage Connector — Docker

The **Google Cloud Storage connector** monitors a GCS bucket and sends objects to DSX for scanning.

It supports:

* **Full scans** of an entire bucket or prefix
* **Continuous monitoring** of new objects
* **Remediation actions** such as delete, move, or tag after malicious verdicts

Monitoring can be triggered using:

* **Google Cloud Pub/Sub notifications (recommended)**
* **Webhook events** from Cloud Run, Cloud Functions, or other middleware

---

## Connector Prerequisites

Before deploying the connector you must create a **Google Cloud service account** with access to the target bucket.

Required:

* A **service account JSON credential**
* Permission to list and read objects

Optional (for remediation actions):

* Permission to move or delete objects

See:

➡️ [Google Cloud Credentials](../../reference/google-cloud-credentials.md)

---

## Minimal Deployment

The following steps will install the connector with minimal configuration changes.  Read the following section for specific configuration details.

The easiest way to deploy the GCS connector is by editing the supplied  `sample.gcs.env` file
and using it with the supplied `docker-compose-google-cloud-storage-connector.yaml` compose file.

### Mount the service account JSON

Place the GCS Service Account JSON credential in the same directory as the compose file.  The default mount path is `/app/creds/gcp-sa.json` to a file named `./gcp-sa.json` in the same directory.  

Excerpt from the compose file:
```yaml
volumes:
  - type: bind
    source: ./gcp-sa.json
    target: /app/creds/gcp-sa.json
    read_only: true
```
As long as the JSON is in the same directory as the compose file, it will be mounted without change to the compose file. 

### Set scan parameters

In this minimal deployment, the connector will scan the bucket `your-bucket` and perform no remediation actions. 

```
# Google Cloud Storage connector env (sample)
# GCS_IMAGE=dsxconnect/google-cloud-storage-connector:0.5.43  # Optional: only need if overriding what's in t eh compose file 
# GOOGLE_APPLICATION_CREDENTIALS=/app/creds/gcp-sa.json       # typically unchanged: container mounted location of GCS service account credentials
DSXCONNECTOR_ASSET=your-bucket                              # Required: GCS bucket
DSXCONNECTOR_FILTER=                                        # Optional: bucket filter to apply
DSX_CONNECTOR_ITEM_ACTION=nothing                           # nothing, move, move_tag, delete
DSX_CONNECTOR_ITEM_ACTION_METAINFO=""                       # if move, where to
```

### Deploy

```bash
docker compose --env-file sample.gcs.env -f docker-compose-google-cloud-storage-connector.yaml up -d
```
That's it.  You should now be able to see the connector in the **DSX-Connect UI**. 

--- 

## Required Settings

{% include-markdown "shared/connectors/_required_settings_env_table.md" %}

{% include-markdown "shared/connectors/_objectstore_required_settings.md" %}

### Advanced Settings
#### Google Cloud Authentication

| Variable                         | Description                                                                     |
| -------------------------------- |---------------------------------------------------------------------------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the mounted service account JSON file, if somewhere other than defaults |
| `GOOGLE_CLOUD_PROJECT`           | Optional project ID if not included in the credential file.                     |


## Monitor Settings

Monitoring enables **on-access scanning** when objects are created or modified.

| Variable                  | Description                                                                 |
| ------------------------- | --------------------------------------------------------------------------- |
| `DSXCONNECTOR_MONITOR`    | Enable monitoring (`true` or `false`).                                      |
| `GCS_PUBSUB_PROJECT_ID`   | Project containing the Pub/Sub subscription receiving bucket notifications. |
| `GCS_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription that receives bucket event notifications.              |
| `GCS_PUBSUB_ENDPOINT`     | Optional override for the Pub/Sub endpoint (useful for local emulators).    |

### Creating a Pub/Sub bucket notification

```bash
gsutil notification create -t gcs-object-events -f json gs://my-bucket
```

Required permissions:

* `roles/storage.objectViewer`
* `roles/pubsub.subscriber`

The connector listens for:

* `OBJECT_FINALIZE`
* `OBJECT_METADATA_UPDATE`

---

### Webhook Alternative

You’d reach for the /webhook/event path instead of native Pub/Sub in a few scenarios:

- Pub/Sub isn’t an option (restricted project, org policy, private cloud, or you’re already forwarding events through something else like Cloud Storage →
  Eventarc → Cloud Run).
- You already have middleware that enriches or filters events and can simply POST to the connector—switching to Pub/Sub would add new moving pieces.
- You want to keep control of retries/backoff or fan out to multiple systems before notifying dsx-connect.
- The connector runs where Pub/Sub access is awkward (air‑gapped network segment, proxies, workload identity gaps), but you can still reach dsx-connect
  over HTTP/S.
- You plan to feed events from several sources beyond Cloud Storage (e.g., a centralized event hub), so hitting the webhook maintains a single integration
  pattern.
- You need custom authentication/validation in front of the connector; a small gateway/service can enforce that and call the webhook.

Pub/Sub remains the simplest path when it’s available, but the webhook keeps things flexible if you’ve already standardized on HTTP callbacks or have
compliance/runtime constraints around Pub/Sub.

For external callbacks into the connector, expose or tunnel the host port mapped to `8630` (compose default). Upstream systems should hit that public address. Internally, set `DSXCONNECTOR_CONNECTOR_URL` to the Docker-service URL (e.g., `http://google-cloud-storage-connector:8630`) so dsx-connect can reach the container.


Instead of Pub/Sub, bucket events can be forwarded to the connector webhook endpoint:

```
POST /webhook/event
```

---

{% include-markdown "shared/_common_connector_docker_tls.md" %}
