# DSXA WebApp File Upload Demo

Minimal example webapp for a loan-processing style intake flow:

- user uploads one or more files
- server scans each file with `dsxa_sdk_py`
- benign files are accepted into an intake folder
- malicious or non-compliant files are rejected and reported back in the UI

## Key Components

- FastAPI entrypoint: `examples/webapp/app.py`
- HTML/CSS/JS page template: `examples/webapp/templates/index.html`
- Upload API route: `upload_and_scan()` in `examples/webapp/app.py`
- Per-file scan logic: `scan_one_upload()` in `examples/webapp/app.py`
- Intake policy decisions: `classify_scan()` in `examples/webapp/policy.py`
- SDK async binary scan call: `AsyncDSXAClient.scan_binary()` in `dsxa_sdk_py/client.py`

The main per-file handoff from the webapp into the SDK happens here:

```python
async with semaphore:
    response: ScanResponse = await client.scan_binary(
        payload,
        custom_metadata=f"loan-intake:{filename}",
    )
```

That code lives in `scan_one_upload()` in `examples/webapp/app.py`.

Inside the SDK, that resolves to the underlying DSXA REST call here:

```python
response = await self._request(
    "POST",
    "/scan/binary/v2",
    headers=headers,
    content=bytes(data),
)
```

That code lives in `AsyncDSXAClient.scan_binary()` in `dsxa_sdk_py/client.py`.

## Install

- Python 3.10+
- Install the webapp dependencies with the SDK extras:

```bash
cd dsxa_sdk_py
pip install -e ".[webapp]"
```

## Configure

```bash
export DSXA_BASE_URL=https://scanner.example.com
export DSXA_AUTH_TOKEN=your-token   # optional if auth is disabled
export DSXA_PROTECTED_ENTITY=1
export DSXA_VERIFY_TLS=true
export WEBAPP_SCAN_CONCURRENCY=4
export WEBAPP_UPLOAD_DIR="demo_uploads/accepted"
```

## Run

```bash
uvicorn examples.webapp.app:app --reload
```

Then open `http://127.0.0.1:8000`.
