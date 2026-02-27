# DIANNA SIEM Prototype CLI

Lightweight CLI prototype to test a SIEM-style DIANNA workflow against DSX-Connect.

## File

- `dianna_siem_cli.py`

## Requirements

- Python 3
- `requests` package (already in `dsx_connect/requirements.txt`)

## Commands

### 1) Enqueue DIANNA from SIEM context

Using `scan_request_task_id` (recommended):

```bash
python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py \
  --base-url http://127.0.0.1:8586 \
  analyze-from-siem \
  --scan-request-task-id c136b7f7-1b68-4f99-979d-f9b36d59f54b
```

Using connector + location:

```bash
python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py \
  --base-url http://127.0.0.1:8586 \
  analyze-from-siem \
  --connector-uuid 26f74f1e-b743-42df-b8b9-12ee8b0d68c9 \
  --location /Users/logangilbert/Documents/dsx-connect-test/app.exe
```

### 2) Fetch DIANNA result by analysis ID

```bash
python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py \
  --base-url http://127.0.0.1:8586 \
  get-result \
  --analysis-id 150
```

Polling example:

```bash
python3 dsx_connect/prototypes/siem_cli/dianna_siem_cli.py \
  --base-url http://127.0.0.1:8586 \
  get-result \
  --analysis-id 150 \
  --attempts 30 \
  --sleep-seconds 2
```

## SIEM callback pattern

In Splunk-style scripted alert action:

1. Parse event fields (e.g., `scan_request_task_id`, `connector_uuid`, `location`).
2. Run `analyze-from-siem`.
3. Capture/derive `analysisId` (from DSX-Connect UI event/log payload).
4. Poll `get-result` until terminal status.
5. Emit result payload back into SIEM as a new event.

## Notes

- `analyze-from-siem` handles quarantine fallback if connector item action moved the file.
- If file cannot be read (deleted/misconfigured action), DSX-Connect returns HTTP 409 with a guidance message.
