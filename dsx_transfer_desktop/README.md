# DSX-Transfer Desktop

DSX-Transfer Desktop is an Electron app for running guarded file-share transfers with a Node-native desktop runner.

The first demo flow copies files from a source folder or mounted file share to a destination folder only after the scanner and transfer policy return an allow decision.

The destination can also be a Google Cloud Storage bucket. GCS writes can use a selected service account JSON file, or Google Application Default Credentials from the desktop process environment when the service account field is blank.

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

## Run a Downloaded macOS Build

Current local/demo builds are unsigned. If macOS blocks the app with a message like "Apple could not verify..." after downloading a `.dmg` or `.zip`, remove the quarantine attribute before launching it:

```bash
xattr -dr com.apple.quarantine "/Applications/DSX-Transfer Desktop.app"
```

If you are testing from an unpacked build instead of `/Applications`, point the command at that `.app` path:

```bash
xattr -dr com.apple.quarantine "/path/to/DSX-Transfer Desktop.app"
```

## Demo Flow

- DSXA scanner: sends file streams through DSXA before commit.
- Verdict actions: benign, malicious, unknown, and error decisions can be mapped to allow or block.
- Filesystem source: source files come from a local folder or mounted share.
- Destination sink: allowed files can be copied to a local folder/mounted share or uploaded to a GCS bucket while preserving source-relative paths.

Each run writes a generated `dsx-transfer.yaml`, audit JSONL, checkpoint file, performance JSONL, and run log under the app user-data directory.

## Configure Destination Sinks

The app currently supports one active destination sink at a time. In the `Destination` pane, use the `Type` selector to choose the active sink. Only the selected sink's fields are used for validation and transfer.

### File Share Destination

Choose `File Share` when the destination is a local folder, external disk, or mounted network share.

1. Select `File Share` in the `Destination` type selector.
2. Set `Destination file share` to the folder where allowed files should be copied.
3. Use `Browse` to choose the folder, or paste the path directly.
4. Run the transfer.

Files are copied under the destination folder using their source-relative paths. For example, if the source contains `invoices/2026/a.pdf`, the destination receives `invoices/2026/a.pdf`.

### GCS Destination

Choose `GCS` when allowed files should be uploaded to a Google Cloud Storage bucket.

1. Select `GCS` in the `Destination` type selector.
2. Set `GCS bucket` to the bucket name only, for example `my-transfer-destination`.
3. Optionally set `Object prefix`, for example `incoming/scanned`.
4. Optionally set `Service account JSON` to a downloaded service account key file.
5. Run the transfer.

The object name is built from the optional prefix plus the source-relative file path. For example, with prefix `incoming/scanned`, source file `invoices/2026/a.pdf` is written to:

```text
gs://my-transfer-destination/incoming/scanned/invoices/2026/a.pdf
```

If `Service account JSON` is blank, the app uses Google Application Default Credentials available to the desktop process. For local demos, using a service account JSON file is usually the most explicit option.

### Create a GCS Service Account

Use a service account with the narrowest bucket access needed for the demo or environment.

1. In Google Cloud, create or choose a project that owns the destination bucket.
2. Create a service account, for example `dsx-transfer-desktop-writer`.
3. Grant it write access to the destination bucket.
   - For a simple demo, grant `Storage Object Admin` on the bucket.
   - For a stricter setup, grant permissions equivalent to creating objects and reading bucket metadata.
4. Create a JSON key for the service account and download it.
5. Store the JSON key somewhere local to the desktop user.
6. In DSX-Transfer Desktop, select `GCS` as the destination type and choose that JSON file in `Service account JSON`.

The desktop app validates the sink by checking that the service account file exists and that the bucket is reachable. During transfer, it uploads allowed files to the selected bucket and prefix.

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
