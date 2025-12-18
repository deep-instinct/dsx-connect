# Developer Test Tasks (Invoke)

This document outlines tasks for testing authentication and local development setups using Invoke.

Authentication smokes and local run helpers live in `test-tasks.py`. Use the `-c` flag to select this collection.

## Prerequisites
- Python 3.12+
- `pip install invoke requests`
- Docker (optional) for spinning up Redis locally

## List Test Tasks
```bash
invoke -c test-tasks -l
```

## Authentication Smoke Tests

### 1) API-only (Enrollment + DSX-HMAC)
```bash
invoke -c test-tasks test-auth
```
What it does:
- Starts Redis (Docker) if available (use `--start-redis=false` to skip)
- Launches `dsx-connect` API with auth enabled
- Registers a dummy connector (X-Enrollment-Token)
- Verifies `POST /dsx-connect/api/v1/scan/auth_check` rejects unsigned requests (401) and accepts DSX‑HMAC (200)

Options:
- `--port=8586`, `--redis-url=redis://localhost:6379/3`, `--enroll-token=<token>`, `--start-redis=false`

### 2) End-to-end (API + filesystem connector)
```bash
invoke -c test-tasks test-auth-connector
```
What it does:
- Launches dsx-connect API and filesystem connector
- Waits for connector registration
- Verifies connector rejects unsigned direct request (401)
- Verifies `dsx-connect` → connector outbound HMAC via `GET /dsx-connect/api/v1/connectors/auth_check/{uuid}`

Options:
- `--api-port=8586`, `--conn-port=8590`, `--redis-url=redis://localhost:6379/3`, `--enroll-token=<token>`, `--start-redis=false`

## Troubleshooting
- If Redis isn’t available, either run a local Redis service or pass `--start-redis=false --redis-url=redis://localhost:6379/3`.
- If the connector doesn’t register in time, the task will print connector logs. Increase the wait window if needed.
