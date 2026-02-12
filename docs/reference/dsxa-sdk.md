# DSXA Python SDK

The DSXA Python SDK is included in this repo under `dsxa_sdk/` and is used by the scan workers to talk to the DSXA scanner.

Key usage:
- `dsxa_sdk.DSXAClient` in `dsx_connect/taskworkers/workers/scan_request.py`
- `DSXAClient.scan_binary(...)` to submit file bytes for scanning

If you need to extend or debug the SDK, start at `dsxa_sdk/README.md` and the `dsxa_sdk` package sources.
