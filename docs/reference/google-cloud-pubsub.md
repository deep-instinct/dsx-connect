# Google Cloud Storage Bucket Notifications with Pub/Sub

Google Cloud Storage monitoring uses bucket notifications that publish object events to a Pub/Sub topic.
The GCS connector consumes a Pub/Sub subscription created by the operator.

This page describes the Google Cloud resources that must exist before enabling `DSXCONNECTOR_MONITOR=true`.

## What Gets Monitored

Bucket monitoring is configured in Google Cloud, not inside DSX-Connect.

For each bucket that should emit object events, configure a Cloud Storage notification that publishes to a Pub/Sub topic.
The connector consumes the subscription attached to that topic.

In DSX-Connect 2, an event is handled only when the bucket or object maps to enabled protection.
Operationally:

* Google Cloud controls which buckets publish events.
* The connector controls which Pub/Sub subscription it consumes.
* DSX-Connect 2 protection controls whether events for a bucket are admitted for scanning/remediation.

If a bucket publishes Pub/Sub events but protection is not enabled for that bucket in DSX-Connect 2, the connector may receive the event, but DSX-Connect 2 should not queue protection work for it.

## Working Variables

Set these variables for the examples below:

```bash
export PROJECT_ID="se-project-388112"
export BUCKET="lg-test-01"
export TOPIC="gcs-object-events"
export SUBSCRIPTION="gcs-events-dsx-connector"
export CONNECTOR_SA_EMAIL="dsx-gcs-connector@${PROJECT_ID}.iam.gserviceaccount.com"
```

## Enable Required APIs

```bash
gcloud services enable storage.googleapis.com pubsub.googleapis.com \
  --project "$PROJECT_ID"
```

## Create the Pub/Sub Topic and Subscription

```bash
gcloud pubsub topics create "$TOPIC" \
  --project "$PROJECT_ID"

gcloud pubsub subscriptions create "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --topic "$TOPIC" \
  --ack-deadline 60
```

The subscription is an operator-created Google Cloud Pub/Sub resource.
This is the value referenced by `GCS_PUBSUB_SUBSCRIPTION` in connector configuration.

## Allow Cloud Storage to Publish

Cloud Storage publishes notifications through a Google-managed service agent.
Grant that service agent permission to publish to the topic:

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
export GCS_SERVICE_AGENT="service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"

gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${GCS_SERVICE_AGENT}" \
  --role "roles/pubsub.publisher"
```

Use the numeric project number only for this service-agent identity.
Connector configuration should use the project ID.

## Create Bucket Notifications

Create a notification on each bucket that should publish object events:

```bash
gcloud storage buckets notifications create "gs://${BUCKET}" \
  --topic "$TOPIC" \
  --payload-format json
```

If your installed `gcloud` does not support `storage buckets notifications create`, use `gsutil`:

```bash
gsutil notification create \
  -t "$TOPIC" \
  -f json \
  "gs://${BUCKET}"
```

Repeat this step for each bucket that should publish events to this topic.

## Grant Connector Access

Grant the connector service account permission to read the bucket and consume the subscription:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/storage.objectViewer"

gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/pubsub.subscriber"
```

If the connector performs quarantine or delete remediation, grant a write-capable bucket role instead of read-only access:

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member "serviceAccount:${CONNECTOR_SA_EMAIL}" \
  --role "roles/storage.objectAdmin"
```

## Verify Google Cloud Configuration

Verify the bucket notification:

```bash
gcloud storage buckets notifications list "gs://${BUCKET}"
```

Verify the subscription:

```bash
gcloud pubsub subscriptions describe "$SUBSCRIPTION" \
  --project "$PROJECT_ID"
```

Optionally upload a test object and pull a message:

```bash
gcloud pubsub subscriptions pull "$SUBSCRIPTION" \
  --project "$PROJECT_ID" \
  --auto-ack
```

You should see a JSON message containing the bucket name and object key.

## Connector Settings

Configure the connector with the Pub/Sub resources created above:

```yaml
env:
  DSXCONNECTOR_MONITOR: "true"
  GCS_PUBSUB_PROJECT_ID: "se-project-388112"
  GCS_PUBSUB_SUBSCRIPTION: "gcs-events-dsx-connector"
```

Settings:

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_MONITOR` | Enables Pub/Sub monitoring when set to `"true"`. |
| `GCS_PUBSUB_PROJECT_ID` | Google Cloud project ID that owns the Pub/Sub subscription. Do not use the numeric project number here. |
| `GCS_PUBSUB_SUBSCRIPTION` | Operator-created Pub/Sub subscription that receives bucket event messages. This can be the subscription name or full path. |
| `GCS_PUBSUB_ENDPOINT` | Optional Pub/Sub endpoint override, mainly for local emulators. |

`GCS_PUBSUB_SUBSCRIPTION` is prefixed with `GCS_` because it identifies a Google Cloud Pub/Sub resource created and owned in Google Cloud.
The connector accepts either:

```text
gcs-events-dsx-connector
```

or:

```text
projects/se-project-388112/subscriptions/gcs-events-dsx-connector
```

The subscription must be attached to the same topic used by the bucket notification.

In native Pub/Sub mode, the connector consumes the subscription directly using Google's client SDK.
It does not use `/webhook/event`.
