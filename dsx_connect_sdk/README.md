# dsx-connect-sdk

Python SDK and CLI for DSX-Connect DIANNA APIs.

## Install

```bash
pip install -e ./dsx_connect_sdk
```

## Python usage

```python
from dsx_connect_sdk import DiannaApiClient

client = DiannaApiClient(base_url="http://127.0.0.1:8586", timeout=20)

enqueue = client.analyze_from_siem(scan_request_task_id="fd052d86-1b5e-4634-993e-2b86567d83d7")

result = client.poll_result_by_task_id(
    enqueue["dianna_analysis_task_id"],
    attempts=30,
    sleep_seconds=2,
)
print(result)
```

## CLI usage

```bash
dsx-dianna --base-url http://127.0.0.1:8586 analyze-from-siem --scan-request-task-id <id>

dsx-dianna --base-url http://127.0.0.1:8586 analyze --scan-request-task-id <id> --attempts 60 --sleep-seconds 2

dsx-dianna --base-url http://127.0.0.1:8586 get-result --dianna-analysis-task-id <task-id> --attempts 30
```

## API surface

- `DiannaApiClient.analyze_from_siem(...)`
- `DiannaApiClient.get_result(analysis_id)`
- `DiannaApiClient.get_result_by_task_id(dianna_analysis_task_id)`
- `DiannaApiClient.poll_result(...)`
- `DiannaApiClient.poll_result_by_task_id(...)`
