# DSX-Transfer Desktop

DSX-Transfer Desktop is the local desktop app for guarded file transfers. It copies or uploads files only after DSXA scanning and transfer policy produce an allow decision.

- [DSX-Transfer Desktop Releases](https://github.com/deep-instinct/dsx-connect/releases?q=dsx-transfer-desktop&expanded=true)

## What It Does

DSX-Transfer Desktop runs a Node-native transfer runner inside an Electron app. The first supported workflow is:

```text
Filesystem source -> DSXA scan -> transfer policy -> active destination sink
```

The current source type is filesystem: a local folder, external disk, or mounted file share.

The active destination sink can be:

- File Share: copy allowed files to a local folder or mounted share.
- GCS: upload allowed files to a Google Cloud Storage bucket.

Only one destination sink is active at a time. In the `Destination` pane, use the `Type` selector to choose the active sink. Only the selected sink's fields are used for validation and transfer.

Each run writes generated run artifacts under the app user-data directory:

- `dsx-transfer.yaml`
- `audit.jsonl`
- `checkpoint.json`
- `perf.jsonl`
- `run.log`

## Quick Start

### 1. Install and Open

Download the desktop build from the release page, install it for your operating system, and open DSX-Transfer Desktop.

If you are using an unsigned or unnotarized internal macOS build, macOS may block the app on first open. First try opening it from Finder with right-click, then **Open**. If macOS still refuses to open it, remove the quarantine attribute:

```bash
xattr -dr com.apple.quarantine "/Applications/DSX-Transfer Desktop.app"
```

For normal end-user distribution, the app should be signed and notarized.

### 2. Configure DSXA

In the `DSXA Connection` panel, enter:

- `Scanner URL`: scanner base URL, for example `http://127.0.0.1:5000`.
- `Auth token (optional)`: leave empty if the scanner does not require an auth token.
- `Protected entity`: DSXA protected entity value, defaulting to `1`.
- `Verify TLS`: enable for proper HTTPS validation; disable only for local development or self-signed test environments.

The app checks that the scanner is reachable and can scan a probe file. A scanner can be reachable but still fail scans if auth or protected-entity values are wrong.

### 3. Choose Source

In the `Source` pane, choose a filesystem source folder or mounted share.

Files are discovered recursively. Destination paths preserve the source-relative structure.

### 4. Configure Destination Sink

In the `Destination` pane, choose the active sink type:

- `File Share`
- `GCS`

The app shows only the fields for the selected sink.

### 5. Run

Choose `Scan and Copy Files` to scan, evaluate policy, and commit allowed files to the active destination.

Use `Cancel` to request cancellation. Cancellation is not immediate; in-flight scans and writes may finish before the run stops.

## File Share Destination

Choose `File Share` when the destination is a local folder, external disk, or mounted network share.

1. Select `File Share` in the `Destination` type selector.
2. Set `Destination file share` to the folder where allowed files should be copied.
3. Use `Browse` to choose the folder, or paste the path directly.
4. Run the transfer.

Files are copied under the destination folder using their source-relative paths. For example, if the source contains:

```text
invoices/2026/a.pdf
```

the destination receives:

```text
invoices/2026/a.pdf
```

## GCS Destination

Choose `GCS` when allowed files should be uploaded to a Google Cloud Storage bucket.

1. Select `GCS` in the `Destination` type selector.
2. Set `GCS bucket` to the bucket name only, for example `my-transfer-destination`.
3. Optionally set `Object prefix`, for example `incoming/scanned`.
4. Optionally set `Service account JSON` to a downloaded service account key file.
5. Run the transfer.

The object name is built from the optional prefix plus the source-relative file path. For example, with prefix `incoming/scanned`, source file:

```text
invoices/2026/a.pdf
```

is written to:

```text
gs://my-transfer-destination/incoming/scanned/invoices/2026/a.pdf
```

If `Service account JSON` is blank, the app uses Google Application Default Credentials available to the desktop process. For local demos, using a service account JSON file is usually the most explicit option.

## Create a GCS Service Account

Use a service account with the narrowest bucket access needed for the demo or environment.

1. In Google Cloud, create or choose a project that owns the destination bucket.
2. Create a service account, for example `dsx-transfer-desktop-writer`.
3. Grant it write access to the destination bucket.
4. Create a JSON key for the service account and download it.
5. Store the JSON key somewhere local to the desktop user.
6. In DSX-Transfer Desktop, select `GCS` as the destination type and choose that JSON file in `Service account JSON`.

For a simple demo, grant `Storage Object Admin` on the bucket. For a stricter setup, grant permissions equivalent to creating objects and reading bucket metadata.

For command-line setup, the equivalent flow is:

```bash
PROJECT_ID="your-project-id"
BUCKET_NAME="your-bucket-name"
SERVICE_ACCOUNT_NAME="dsx-transfer-desktop-writer"
KEY_FILE="$HOME/dsx-transfer-desktop-writer.json"

gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
  --project "$PROJECT_ID" \
  --display-name "DSX-Transfer Desktop Writer"

gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
  --member "serviceAccount:${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/storage.objectAdmin"

gcloud iam service-accounts keys create "$KEY_FILE" \
  --iam-account "${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project "$PROJECT_ID"
```

Then set `Service account JSON` in the app to the generated `KEY_FILE`.

## Run From Source

From the repository root:

```bash
cd dsx_transfer_desktop
npm install
npm run dev
```

## Build Installers

```bash
cd dsx_transfer_desktop
npm run build:mac
npm run build:win
```

The packaged app uses Electron's bundled Node.js runtime. It does not require a system Python runtime.
