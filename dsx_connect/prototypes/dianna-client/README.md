# DIANNA API Client Prototype

This folder contains:

- `test_dianna_api_client_cli.py`: Typer-based CLI test harness for local validation
- `dianna_api_client.py`: compatibility shim that re-exports SDK client classes

The reusable implementation now lives in `dsx_connect_sdk/`.

## Requirements

- Python 3
- `requests` and `typer` (see `dsx_connect/requirements.txt`)
- SDK import path available (either `pip install -e ./dsx_connect_sdk` or run from repo root)

## CLI Examples

Enqueue analysis from SIEM context:

```bash
python3 dsx_connect/prototypes/dianna-client/test_dianna_api_client_cli.py \
  --base-url http://127.0.0.1:8586 \
  analyze-from-siem \
  --scan-request-task-id fd052d86-1b5e-4634-993e-2b86567d83d7
```

Fetch result by DIANNA analysis id:

```bash
python3 dsx_connect/prototypes/dianna-client/test_dianna_api_client_cli.py \
  --base-url http://127.0.0.1:8586 \
  get-result \
  --analysis-id 150
```

Fetch result directly by DSX task id:

```bash
python3 dsx_connect/prototypes/dianna-client/test_dianna_api_client_cli.py \
  --base-url http://127.0.0.1:8586 \
  get-result \
  --dianna-analysis-task-id 5acacaaf-29b6-43c1-b73f-e0febffcbeff
```

Poll result until terminal state:

```bash
python3 dsx_connect/prototypes/dianna-client/test_dianna_api_client_cli.py \
  --base-url http://127.0.0.1:8586 \
  get-result \
  --analysis-id 150 \
  --attempts 30 \
  --sleep-seconds 2
```

## Using in SIEM code

Minimal usage from Python:

```python
from dsx_connect_sdk import DiannaApiClient

client = DiannaApiClient(base_url="http://127.0.0.1:8586", timeout=20)

enqueue = client.analyze_from_siem(scan_request_task_id="...")
analysis_id = "150"  # derive from DIANNA event/log payload
result = client.poll_result(analysis_id, attempts=30, sleep_seconds=2)
print(result)
```

Notes:

- `get_result` can use either DIANNA `analysisId` (`--analysis-id`) or DSX worker task id (`--dianna-analysis-task-id`).
- CLI supports typo-compatible `--analyis-id` as alias for `--analysis-id`.
