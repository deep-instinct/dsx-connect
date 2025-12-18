# Google Cloud Storage Connector — Docker Compose

This guide shows how to deploy the Google Cloud Storage connector with Docker Compose for quick testing/POV.
Google Cloud Storage connectors support both full scan (on-demand) and continuous monitoring (on-access) scanning, as well as the ability to perform
remediation actions on files (delete/move/tag/move and tag).

For monitoring, users have two options:

  - Use Google Cloud Pub/Sub notifications to trigger the connector (recommended)
  - Use Cloud Run/Cloud Functions on Google Cloud to monitor the bucket and trigger the connector via the /webhook/event API.

Pub/Sub notifications are the recommended approach, as it requires less maintenance and the extra step of monitoring middleware to send the connector
events.  

## Prerequisites
- Docker installed locally (or a container VM)
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Examples below assume the extracted folder is `dsx-connect-<core_version>/`. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- A GCP service account JSON secret (mounted into the container) with permissions to list/read (and optionally write/move/delete) objects — see Reference → [Google Cloud Credentials](../../reference/google-cloud-credentials.md) for setup details.
- A Docker network shared with dsx‑connect (example: `dsx-connect-network`)

## Compose File

In the extracted bundle, use `dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/docker-compose-google-cloud-storage-connector.yaml`.

### Core connector env (common across connectors)

| Variable | Description                                                                                                                                         |
| --- |-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `DSXCONNECTOR_DSX_CONNECT_URL` | dsx-connect base URL (use `http://dsx-connect-api:8586` on the shared Docker network).                                                              |
| `DSXCONNECTOR_CONNECTOR_URL` | Callback URL dsx-connect uses to reach the connector (defaults to the service name inside the Docker network).                                      |
| `DSXCONNECTOR_ASSET` | Root bucket and/or `bucket/prefix` to scan and monitor.                                                                                             |
| `DSXCONNECTOR_FILTER` | Optional rsync‑style include/exclude rules relative to the asset.                                                                                   |
| `DSXCONNECTOR_ITEM_ACTION` | What to do on malicious verdicts (`nothing`, `delete`, `move`, `move_tag`). Use `move`/`move_tag` to relocate objects after verdict.                |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Destination bucket/prefix for moved objects when using `move`/`move_tag`.                                                                           |
| `DSXCONNECTOR_MONITOR` | Enable change monitoring (`true`/`false`). Requires Pub/Sub notifications.  (note, if using Webhook style notification, this flag can remain false) |


### Google Cloud-specific settings

| Variable | Description                                                                                                                                     |
| --- |-------------------------------------------------------------------------------------------------------------------------------------------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to the mounted service account JSON (e.g., `/app/creds/service-account.json`).                                                             |
| `GOOGLE_CLOUD_PROJECT` | Optional—used when the service account JSON omits `project_id`.                                                                                 |
| `GCS_PUBSUB_PROJECT_ID` | (if `DSXCONNECTOR_MONITOR: true`) GCP project that owns the Pub/Sub subscription receiving bucket events.                                       |
| `GCS_PUBSUB_SUBSCRIPTION` | (if `DSXCONNECTOR_MONITOR: true`) Subscription name or full resource path (e.g., `gcs-object-events` or `projects/<proj>/subscriptions/<sub>`). |
| `GCS_PUBSUB_ENDPOINT` | Override Pub/Sub endpoint (useful for local emulators). Leave blank for production.                                                             |

The Project ID should match the Service Account JSON file value (which was applied as a secret above).  Subscription name is the name of the Pub/Sub subscription
that receives bucket events, which was create as part of the service account setup.

## Minimal Deployment

### Mount your service‑account JSON.

Create a google service account and download the JSON: [Google Cloud Credentials](../../../reference/google-cloud-credentials.md).  Place the JSON next to the compose file (or use an absolute path), or anywhere that the deployed docker container can access on the host system.
The default mount path is `/app/creds/gcp-sa.json` to a file named `gcp-sa.json` in the same directory. The easiet deployment with no changes needed is to
name the JSON file `gcp-sa.json` and place it in the same directory as the compose file.:
```yaml
      # Mount a Google service account JSON and point GOOGLE_APPLICATION_CREDENTIALS to it
      - type: bind
        source: ./gcp-sa.json
        target: /app/creds/gcp-sa.json
        read_only: true
        bind:
          selinux: z
```
If you wish to use a different filename, change the `source` path to the desired filename.

### Deploy the connector
Support full-scan bucket, no monitoring, no remediation:

- DSXCONNECTOR_ASSET: "bucket name"
- DSXCONNECTOR_ITEM_ACTION: "nothing" # <-- the default

Deploy:
```bash
cp dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/.sample.gcs.env \
  dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/.env
# edit dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/.env (asset, creds path, Pub/Sub, etc.)
docker compose --env-file dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/google-cloud-storage-connector-<connector_version>/docker-compose-google-cloud-storage-connector.yaml up -d
```

### Test Scan
If you just have the connector running (no dsx-connect), you still navigate to the connector's API page:
http://localhost:8630/docs

This confirms that the connector is running and listening on port 8630.  From the OpenAPI docs you can invoke a full scan by POSTing to the connector's full_scan endpoint, 
and you should see the following response:

```json
{
  "status": "success",
  "message": "Full scan initiated",
  "description": "The scan is running in the background. job_id=06930255-a48b-443a-840f-414a2659855e",
  "id": null,
  "preview": null
}
```
If you have dsx-connect running, navigate to the DSX-Connect UI, note the Google Cloud Storage 'card' and click the `Full Scan` button, to invoke a scan.

## Assets and Filters
- `DSXCONNECTOR_ASSET` should be set to your bucket (e.g., `my-bucket`) or `bucket/prefix` to scope listings.
- If a prefix is provided, listings start at that sub‑root and filters are evaluated relative to it.
- See Reference → [Assets & Filters](../../reference/assets-and-filters.md) for sharding/partition guidance.

## Monitoring
- Use `DSXCONNECTOR_ASSET` to set the bucket (and optional prefix) to monitor.
- If Pub/Sub monitoring is enabled, the connector listens to Pub/Sub in a background thread. Create a bucket notification that publishes to the subscription; for example:
  ```bash
  gsutil notification create -t gcs-object-events -f json gs://my-bucket
  ```
  
  The service account must have `roles/storage.objectViewer` on the bucket and `roles/pubsub.subscriber` on the subscription.
  The connector listens for `OBJECT_FINALIZE` (new/updated object) and `OBJECT_METADATA_UPDATE` events; these are fixed defaults.
  See Reference → [Google Cloud Credentials](../../reference/google-cloud-credentials.md) for the full setup commands.

## TLS Options
See [Deploying with SSL/TLS](./tls.md) for Docker Compose examples (core + connectors), including runtime-mounted certs and local-dev self-signed cert generation.

## Webhooks: When and How to Expose

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
