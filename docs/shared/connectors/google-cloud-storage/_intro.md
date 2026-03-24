The **Google Cloud Storage connector** monitors a GCS bucket and sends objects to DSX for scanning.

It supports:

* **Full scans** of an entire bucket or prefix
* **Continuous monitoring** of new objects
* **Remediation actions** such as delete, move, or tag after malicious verdicts

Monitoring can be triggered using:

* **Google Cloud Pub/Sub notifications (recommended)**
* **Webhook events** from Cloud Run, Cloud Functions, or other middleware
