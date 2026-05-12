# DSXA FastAPI Upload Demo

Minimal example webapp for a loan-processing style intake flow:

- user uploads one or more files
- server scans each file with `dsxa_sdk_py`
- benign files are accepted into an intake folder
- malicious or non-compliant files are rejected and reported back in the UI

## Install

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
export WEBAPP_UPLOAD_DIR="$(pwd)/.demo_uploads/accepted"
```

## Run

```bash
uvicorn examples.webapp.app:app --reload
```

Then open `http://127.0.0.1:8000`.
