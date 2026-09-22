# dsx-connect-sdk

Python SDK and CLI for DSX-Connect APIs.

## Install

```bash
pip install -e ./dsx_connect_sdk
```

## Domain-oriented client (recommended)

The SDK mirrors FastAPI router groups using domain sub-clients.

```python
import asyncio
from dsx_connect_sdk import DSXConnectClient

async def main() -> None:
    sdk = DSXConnectClient(base_url="http://127.0.0.1:8586")

    cfg = await sdk.core.get_config()
    print(cfg)

    # scan request
    # await sdk.scan.request({...})

    # connector lifecycle
    # await sdk.connectors.register({...}, enrollment_token="...")

    # DIANNA
    # enqueue = sdk.dianna.analyze_from_siem(scan_request_task_id="...")

asyncio.run(main())
```

Available domains:
- `sdk.core`
- `sdk.scan`
- `sdk.connectors`
- `sdk.dianna`
- `sdk.results` (placeholder)
- `sdk.sse` (placeholder)

## Python usage (compatibility classes)

### DIANNA APIs

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

### Core APIs (async)

```python
import asyncio
from dsx_connect_sdk import DSXConnectCoreApiClient

async def main() -> None:
    core = DSXConnectCoreApiClient(base_url="http://127.0.0.1:8586")
    cfg = await core.get_config()
    print(cfg)

asyncio.run(main())
```

## CLI usage

The `dsx-dianna` CLI uses `DSXConnectClient(...).dianna` internally.

```bash
dsx-dianna --base-url http://127.0.0.1:8586 analyze-from-siem --scan-request-task-id <id>

dsx-dianna --base-url http://127.0.0.1:8586 analyze --scan-request-task-id <id> --attempts 60 --sleep-seconds 2

dsx-dianna --base-url http://127.0.0.1:8586 get-result --dianna-analysis-task-id <task-id> --attempts 30
```

## API surface

### Root client
- `DSXConnectClient(...).core`
- `DSXConnectClient(...).scan`
- `DSXConnectClient(...).connectors`
- `DSXConnectClient(...).results`
- `DSXConnectClient(...).sse`
- `DSXConnectClient(...).dianna`

### Core domain
- `sdk.core.get_config()`
- `sdk.core.connection_test()`

### Scan domain
- `sdk.scan.request(payload)`
- `sdk.scan.request_batch(payload)`
- `sdk.scan.enqueue_done(job_id, payload)`

### Connectors domain
- `sdk.connectors.register(payload, enrollment_token=...)`
- `sdk.connectors.unregister(connector_uuid)`

### DIANNA domain
- `sdk.dianna.analyze_from_siem(...)`
- `sdk.dianna.get_result(analysis_id)`
- `sdk.dianna.get_result_by_task_id(dianna_analysis_task_id)`
- `sdk.dianna.poll_result(...)`
- `sdk.dianna.poll_result_by_task_id(...)`
