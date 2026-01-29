# Advanced Settings

This page documents environment selection and worker retry policy behavior.

## Environment selection

The app environment is controlled by `DSXCONNECT_APP_ENV`, which maps to `AppEnv` in `dsx_connect/config.py`.
This value directly influences behavior across the DSX-Connect core (including worker retry policy defaults and other environment-specific logic).

Supported values:

- `dev`
- `stg`
- `prod`

Defaults:

- If `DSXCONNECT_APP_ENV` is not set, the default is `dev`.
- Local dev loads `dsx_connect/.dev.env` by default. Set `DSXCONNECT_SKIP_DEVENV=1` to ignore it.

Example:
```
DSXCONNECT_APP_ENV=stg python dsx_connect/dsx-connect-api-start.py
```

## Worker retry policy

Worker retry policy is defined in `dsx_connect/taskworkers/policy.py`. It is derived from a base policy (configured via env vars) and then overridden based on the selected environment.

Base policy (configurable via `DSXCONNECT_WORKERS__*`):

- `DSXCONNECT_WORKERS__SCAN_REQUEST_MAX_RETRIES`: number of retry attempts for the scan request worker when reading a file and sending it to DSXA.
- `DSXCONNECT_WORKERS__CONNECTOR_RETRY_BACKOFF_BASE`: base seconds for exponential backoff when retrying connector-related errors.
- `DSXCONNECT_WORKERS__DSXA_RETRY_BACKOFF_BASE`: base seconds for exponential backoff when retrying DSXA-related errors.
- `DSXCONNECT_WORKERS__SERVER_ERROR_RETRY_BACKOFF_BASE`: base seconds for exponential backoff on internal/server errors.
- `DSXCONNECT_WORKERS__RETRY_CONNECTOR_CONNECTION_ERRORS`: retry on connector connection failures.
- `DSXCONNECT_WORKERS__RETRY_CONNECTOR_SERVER_ERRORS`: retry on connector 5xx responses.
- `DSXCONNECT_WORKERS__RETRY_CONNECTOR_CLIENT_ERRORS`: retry on connector 4xx responses.
- `DSXCONNECT_WORKERS__RETRY_DSXA_CONNECTION_ERRORS`: retry on DSXA connection failures.
- `DSXCONNECT_WORKERS__RETRY_DSXA_TIMEOUT_ERRORS`: retry on DSXA timeouts.
- `DSXCONNECT_WORKERS__RETRY_DSXA_SERVER_ERRORS`: retry on DSXA 5xx responses.
- `DSXCONNECT_WORKERS__RETRY_DSXA_CLIENT_ERRORS`: retry on DSXA 4xx responses.

Default base values (used unless overridden by env or by an environment policy):

| Setting | Default |
| --- | --- |
| `DSXCONNECT_WORKERS__SCAN_REQUEST_MAX_RETRIES` | `1` |
| `DSXCONNECT_WORKERS__CONNECTOR_RETRY_BACKOFF_BASE` | `5` |
| `DSXCONNECT_WORKERS__DSXA_RETRY_BACKOFF_BASE` | `3` |
| `DSXCONNECT_WORKERS__SERVER_ERROR_RETRY_BACKOFF_BASE` | `5` |
| `DSXCONNECT_WORKERS__RETRY_CONNECTOR_CONNECTION_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_CONNECTOR_SERVER_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_CONNECTOR_CLIENT_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_DSXA_CONNECTION_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_DSXA_TIMEOUT_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_DSXA_SERVER_ERRORS` | `true` |
| `DSXCONNECT_WORKERS__RETRY_DSXA_CLIENT_ERRORS` | `true` |

Environment overrides (default values for each environment):

| Environment | max_retries | connector_backoff_base | dsxa_backoff_base | server_backoff_base | retry_connector_client_errors | retry_dsxa_client_errors |
| --- | --- | --- | --- | --- | --- | --- |
| dev | 1 | 5 | 3 | 5 | true | true |
| stg | 3 | 30 | (base) | 15 | true | true |
| prod | 5 | (base) | (base) | (base) | false | false |

Notes:
- Any value marked as `(base)` comes from the `DSXCONNECT_WORKERS__*` settings.
- All other retry flags inherit from base unless explicitly overridden above.

## Throughput and scan stats

Throughput depends on connector IO, DSXA scan time, worker concurrency, and network conditions.
To help you measure real performance in your environment, DSX-Connect tracks per-job metrics in Redis and exposes them via the job status API:

```
GET /dsx-connect/api/v1/scan/jobs/{job_id}
```

Key fields (per job):

- `started_at`: first time the job began enqueueing items (seconds since epoch).
- `first_scan_started_at` / `last_scan_started_at`: when workers actually began processing items.
- `first_completed_at` / `last_completed_at`: when results started/finished.
- `finished_at`: job completion timestamp (when processed >= total).
- `enqueued_count` / `processed_count`: items queued vs. completed.
- `total_bytes`: total bytes scanned in the job.
- `total_scan_time_us`: sum of DSXA scan times for all files.
- `total_request_elapsed_ms`: end-to-end time in dsx-connect (read + upload + DSXA response), summed across files.

Derived fields (computed in the API response):

- `avg_bytes_per_file`
- `avg_request_elapsed_ms`
- `scan_us_per_byte` (DSXA scan time per byte)
- `scan_bytes_per_sec` (DSXA throughput)
- `request_bytes_per_sec` (end-to-end throughput)
- `processing_window_secs` (first scan start to last completion)

Practical guidance:

- Use `scan_bytes_per_sec` to compare DSXA performance across different deployment configurations of workers/scanners.
- Use `request_bytes_per_sec` to capture connector + network + DSXA end-to-end throughput.
- Increase `dsx_connect_scan_request_worker` concurrency to raise throughput when DSXA and IO are not saturated.
- Compare per-job metrics before/after tuning worker concurrency, DSXA resources, or connector settings.

UI tip:

- In the UI header, use the “Compare Jobs” icon to select multiple job IDs and view a side‑by‑side throughput table.

## Policy variants (optional)

The retry policy module includes named variants for special cases:
- `high_throughput`
- `critical_files`
- `circuit_breaker`

These are loaded via `load_policy_variant()` and are not tied to `DSXCONNECT_APP_ENV`.
