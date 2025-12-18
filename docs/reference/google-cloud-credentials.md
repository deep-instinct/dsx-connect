# Google Cloud Credentials

Use these steps to configure the Google Cloud Storage connector with the necessary permissions for both object access and Pub/Sub monitoring.

## 1. Enable APIs
```bash
gcloud services enable storage.googleapis.com pubsub.googleapis.com
```
## 2. Service account and roles
Connectors use a service account to access the bucket, and a Pub/Sub subscription to receive notifications.  To do this they will need a
Service Account Key.  Two options are available:
  - Option A: Create a new service account and key
  - Option B: Use an existing service account and key

The following steps will walk you through Option A, creating a new service account and key.  If you want to use an existing service account,
then you simply need to add necessary roles to the service account, if they don't already exist.
Create a service account and grant the necessary roles for on-access (monitoring) and on-demand (full scan).

- Full Scan on a bucket requires the `storage.objectView` role if just scanning files, and `storage.objectAdmin` if you need to move/delete files for remediation.
- Monitoring the bucket requires the `storage.objectViewer` role and the `pubsub.subscriber` role on the subscription.

```bash
PROJECT_ID=<your-project-id>
SA_NAME=gcs-dsx-connector
SUBSCRIPTION=gcs-events-dsx-connector

# Create service account
gcloud iam service-accounts create $SA_NAME \
  --display-name="GCS DSX-Connector"

# Bucket read access - needed for Pub/Sub monitoring and scanning
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/storage.objectViewer

# Bucket write access if you need move/delete on a bucket
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/storage.objectAdmin

```

## 3. Bucket notifications (for monitoring)
Each bucket you want to monitor must publish to the Pub/Sub topic. Run the notification command once per bucket. The connector filters events by `DSXCONNECTOR_ASSET`/`DSXCONNECTOR_FILTER`.
```bash
gsutil notification create -t gcs-object-events -f json gs://YOUR_BUCKET
```

```bash
# Create the subscription and grant subscriber role
gcloud pubsub subscriptions create $SUBSCRIPTION \
  --topic gcs-object-events

gcloud pubsub subscriptions add-iam-policy-binding \
  projects/$PROJECT_ID/subscriptions/$SUBSCRIPTION \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/pubsub.subscriber

```
`OBJECT_FINALIZE` and metadata update events now flow into the subscription. Repeat the `gsutil notification create` command for every bucket that should trigger events. The connector uses `DSXCONNECTOR_ASSET` and `DSXCONNECTOR_FILTER` to decide which objects to process.


## 4. Service account key (Option A - if you want a new key for the connector)
Create a service account key (JSON) for the connector.
```bash
gcloud iam service-accounts keys create gcs-sa.json \
  --iam-account ${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com
```
See deployment guides on how to use/mount the JSON with the `GOOGLE_APPLICATION_CREDENTIALS` setting.

## 5. Connector configuration
```env
GOOGLE_APPLICATION_CREDENTIALS=/app/creds/gcp-sa.json
DSXCONNECTOR_ASSET=YOUR_BUCKET
DSXCONNECTOR_MONITOR=true
GCS_PUBSUB_PROJECT_ID=<your-project-id>
GCS_PUBSUB_SUBSCRIPTION=$SUBSCRIPTION
```
Install dependencies (if running locally):
```bash
pip install google-cloud-storage google-cloud-pubsub
```

> Pub/Sub monitoring now always listens for `OBJECT_FINALIZE` and `OBJECT_METADATA_UPDATE` events. Any legacy `*_MONITOR_EVENT_TYPES` variables are ignored.

## 7. Alternative webhook
If you want to use the connector without Pub/Sub, you can use the connector webhook. Deploy Cloud Functions/Run that receive events on buckets and use it to send object metainfo to `/google-cloud-storage-connector/webhook/event`. Both use the same handler.

## 8. Role summary
- `roles/storage.objectViewer` (plus `storage.objectAdmin` if you use move/delete).
- `roles/pubsub.subscriber` on the subscription.
