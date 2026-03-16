# Configure Google Cloud Storage Bucket Notifications with Pub/Sub (gcloud CLI)

## 1. Create a Pub/Sub Topic

```bash
gcloud pubsub topics create dsx-gcs-notifications
```

This topic will receive events whenever objects are created in the bucket.

---

## 2. Get the Project Number

```bash
gcloud projects describe PROJECT_ID --format="value(projectNumber)"
```
where `PROJECT_ID` is the name of your project.

Example output:

```
123456789012
```

Save this value — it will be used to grant permissions to the Cloud Storage service account.

---

## 3. Allow Cloud Storage to Publish to the Topic

```bash
gcloud pubsub topics add-iam-policy-binding dsx-gcs-notifications \
  --member=serviceAccount:service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com \
  --role=roles/pubsub.publisher
```

Replace `PROJECT_NUMBER` with the number obtained in the previous step.

---

## 4. Create the Bucket Notification

```bash
gcloud storage buckets notifications create gs://BUCKET_NAME \
  --topic=dsx-gcs-notifications \
  --event-types=OBJECT_FINALIZE \
  --payload-format=json
```

**OBJECT_FINALIZE** triggers when a file upload is completed.

---

## 5. Create a Pub/Sub Subscription

```bash
gcloud pubsub subscriptions create dsx-gcs-sub \
  --topic=dsx-gcs-notifications
```

The **subscription ID** is the name used above (`dsx-gcs-sub`).

---

## (Optional) Test the Notification

Upload a file to the bucket, then pull messages:

```bash
gcloud pubsub subscriptions pull dsx-gcs-sub --auto-ack
```

You should see a JSON message containing the bucket name and object key.

