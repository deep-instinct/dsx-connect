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

## Policy variants (optional)

The retry policy module includes named variants for special cases:
- `high_throughput`
- `critical_files`
- `circuit_breaker`

These are loaded via `load_policy_variant()` and are not tied to `DSXCONNECT_APP_ENV`.
