# Python SDK Calls

This page documents the callable surface of the Python DSXA SDK.

Source: `dsxa_sdk_py/dsxa_sdk_py/client.py`

## Clients

## `DSXAClient` (sync)

Constructor:

```python
DSXAClient(
    base_url: str,
    auth_token: str | None = None,
    timeout: float | None = 30.0,
    verify_tls: bool | str = True,
    http_proxy: str | None = None,
    default_protected_entity: int | None = 1,
    default_metadata: str | None = None,
)
```

## `AsyncDSXAClient` (async)

Constructor has the same parameters as `DSXAClient`.

---

## Core scan calls

## `scan_binary(data, ...)`

Scans raw bytes via `POST /scan/binary/v2`.

Optional args:
- `protected_entity`
- `custom_metadata`
- `password`
- `base64_header`

## `scan_binary_stream(data_iterable, ...)`

Scans streamed bytes via `POST /scan/binary/v2` (chunked transfer).

Use this for large payloads to avoid buffering entire files in memory.

## `scan_base64(encoded_data, ...)`

Scans base64 payload via `POST /scan/base64/v2`.

## `scan_file(path, mode=ScanMode.BINARY, ...)`

Convenience helper that reads a file from disk, then scans it.

`mode` values:
- `ScanMode.BINARY`
- `ScanMode.BASE64`

## `scan_hash(file_hash, ...)`

Scans by hash via `POST /scan/by_hash`.

## `scan_by_path(stream_path, ...)`

Starts scan-by-path workflow via `GET /scan/by_path` with `Stream-Path` header.

## `get_scan_by_path_result(scan_guid)`

Gets current scan-by-path result via `POST /result/by_path`.

## `poll_scan_by_path(scan_guid, interval_seconds=5.0, timeout_seconds=900.0)`

Polls until terminal verdict or timeout.

---

## Lifecycle calls

## Sync client
- `close()`
- context manager support:
  - `with DSXAClient(...) as client: ...`

## Async client
- `aclose()`
- async context manager support:
  - `async with AsyncDSXAClient(...) as client: ...`

---

## Typical usage

## Disk file scan (sync)

```python
from dsxa_sdk_py.client import DSXAClient, ScanMode

with DSXAClient(base_url="http://127.0.0.1:5000", auth_token=None, verify_tls=False) as client:
    resp = client.scan_file(
        "/path/to/file.pdf",
        mode=ScanMode.BINARY,
        custom_metadata="upload-id=1234",
    )
    print(resp.verdict, resp.scan_guid)
```

## Upload stream scan (async)

```python
import asyncio
from dsxa_sdk_py.client import AsyncDSXAClient

async def chunker(upload_stream, chunk_size=1024 * 1024):
    while True:
        chunk = await upload_stream.read(chunk_size)
        if not chunk:
            break
        yield chunk

async def scan_upload(upload_stream):
    async with AsyncDSXAClient(base_url="http://127.0.0.1:5000", verify_tls=False) as client:
        return await client.scan_binary_stream(
            chunker(upload_stream),
            custom_metadata="source=web-upload",
        )
```

## Bounded concurrency pattern (async)

```python
import asyncio
from pathlib import Path
from dsxa_sdk_py.client import AsyncDSXAClient

async def scan_many(paths: list[Path], concurrency: int = 8):
    sem = asyncio.Semaphore(concurrency)
    async with AsyncDSXAClient(base_url="http://127.0.0.1:5000", verify_tls=False) as client:
        async def one(path: Path):
            async with sem:
                return await client.scan_file(str(path))
        return await asyncio.gather(*(one(p) for p in paths), return_exceptions=True)
```

---

## Notes

- There is no single SDK \"batch endpoint\" call; batching is done by running many scan calls concurrently.
- Reuse a single client instance per run to benefit from connection pooling.
- The Python CLI is useful for three things: baselining DSXA throughput, scanning files/folders from the command line, and serving as runnable example code for SDK users.
- The Python CLI `scan-files` and `scan-folder` commands default to concurrency `4` and print `Concurrency: <N>` in the final summary output.
