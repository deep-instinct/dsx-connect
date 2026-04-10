# Google Cloud Storage Connector — Docker

{% include-markdown "shared/connectors/google-cloud-storage/_intro.md" %}

---

## Prerequisites

{% include-markdown "shared/connectors/google-cloud-storage/_prerequisites.md" %}

---

## Minimal Deployment

The following steps will install the connector with minimal configuration changes, supporting full-scan only. 

!!! tip "Using the Docker bundle"

    All Docker connector deployments use the official **DSX-Connect Docker bundle**, which contains the compose files and sample environment files for each connector.
    
    [DSX-Connect Docker bundles](https://github.com/deep-instinct/dsx-connect/releases)

Download the DSX-Connect Docker bundle and navigate to the Google Cloud Storage connector directory:
`dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/`

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
DSX_CONNECTOR_ITEM_ACTION_MOVE_METAINFO=""                       # if move, where to
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

### Connector-specific Settings

#### Google Cloud Authentication

| Variable                         | Description                                                                     |
| -------------------------------- |---------------------------------------------------------------------------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the mounted service account JSON file, if somewhere other than defaults |
| `GOOGLE_CLOUD_PROJECT`           | Optional project ID if not included in the credential file.                     |



### Advanced Settings

#### DSX_Connect Authentication

{% include-markdown "shared/connectors/_common_connector_authentication.md" %}

#### TLS

{% include-markdown "shared/_common_connector_docker_tls.md" %}


## Monitor Settings

Monitoring enables **on-access scanning** when objects are created or modified.


### Google Notification via Pub/Sub

First, set up notifications for the bucket you want to monitor.
[Pub/Sub Setup](../../reference/google-cloud-pubsub.md)

Next, configure the Pub/Sub settings from that setup.

Important distinctions:

- `GCS_PUBSUB_PROJECT_ID` is the GCP project ID, for example `se-project-388112`.
- Do not use the numeric project number here. The project number is only used during the IAM publisher-binding step in the Pub/Sub setup guide.
- `GCS_PUBSUB_SUBSCRIPTION` is the Pub/Sub subscription name or full subscription path.
- In the Google Cloud Console, this is the subscription shown on the Subscriptions page. The connector accepts either:
  - the subscription name you created, for example `dsx-gcs-sub`
  - the full subscription path for that same subscription, for example `projects/<project-id>/subscriptions/dsx-gcs-sub`

The subscription must be attached to the same topic used by the bucket notification.

| Variable                  | Description                                                                 |
| ------------------------- | --------------------------------------------------------------------------- |
| `DSXCONNECTOR_MONITOR`    | Enable monitoring (`true` or `false`).                                      |
| `GCS_PUBSUB_PROJECT_ID`   | GCP project ID that owns the Pub/Sub subscription.                          |
| `GCS_PUBSUB_SUBSCRIPTION` | Pub/Sub subscription name or full path that receives bucket event messages. |
| `GCS_PUBSUB_ENDPOINT`     | Optional override for the Pub/Sub endpoint (useful for local emulators).    |

The connector consumes Pub/Sub directly using Google's client SDK. It does not use `/webhook/event` when running in native Pub/Sub mode.

Example:

```env
DSXCONNECTOR_MONITOR=true
GCS_PUBSUB_PROJECT_ID=se-project-388112
GCS_PUBSUB_SUBSCRIPTION=projects/se-project-388112/subscriptions/dsx-gcs-sub
```

---

### Webhook Alternative

You’d reach for the connector's /webhook/event path instead of native Pub/Sub in a few scenarios:

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

For external callbacks into the connector, expose or tunnel the host port mapped to `8630` (compose default). 
Upstream systems should hit that public address. Internally, set `DSXCONNECTOR_CONNECTOR_URL` to the Docker-service URL 
(e.g., `http://google-cloud-storage-connector:8630`) so dsx-connect can reach the container.

