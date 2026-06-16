# Demo 01: New Filesystem-to-GCS Transfer

Use this after running `DSX-Transfer: Create New Transfer`, choosing a directory, and editing the generated annotated `dsx-transfer.yaml`.

## 1. Make The Config Active

With the generated `dsx-transfer.yaml` open in VS Code, run:

```text
DSX-Transfer: Use Active File as Config
```

## 2. Validate The Config

Run:

```text
DSX-Transfer: Validate Config
```

Fix anything it reports. Common issues:

- source path missing
- placeholder `gs://REPLACE_WITH_BUCKET/archive`
- missing `GOOGLE_APPLICATION_CREDENTIALS`
- scanner URL still `https://scanner.example.com`

## 3. Set GCS Credentials

If not already set, add this to VS Code workspace settings:

```json
{
  "dsxTransfer.extraEnv": {
    "GOOGLE_APPLICATION_CREDENTIALS": "/real/path/to/service-account.json"
  }
}
```

## 4. Run The Transfer

Run:

```text
DSX-Transfer: Run Transfer
```

## 5. Inspect Results

Open the DSX-Transfer activity view and inspect `Last Report`:

- planned count
- allowed count
- blocked count
- failed count
- blocked/failed item JSON if needed

## 6. Run The Generated Python Skeleton

From the generated transfer workspace:

```bash
cd /path/to/your/transfer-workspace/integration/python
DSX_TRANSFER_WORKSPACE=/Users/logangilbert/PycharmProjects/dsx-connect \
DSX_TRANSFER_CONFIG=/path/to/your/transfer-workspace/dsx-transfer.yaml \
DSX_TRANSFER_PYTHON=/Users/logangilbert/PycharmProjects/dsx-connect/.venv/bin/python \
DSX_TRANSFER_PYTHONPATH=.:dsx_transfer:dsxa_sdk_py \
python run_transfer.py
```

This proves the same config works through the generated app-facing skeleton.
