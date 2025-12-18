# dsx-connect Core — Docker Compose

This guide walks through running the full dsx-connect platform (API + workers + Redis + optional log collector + optional DSXA scanner) using the Docker Compose bundle release. Examples below assume you downloaded and extracted `dsx-connect-compose-bundle-<core_version>.tar.gz`, which expands to `dsx-connect-<core_version>/`.

## Files in This Package

Path: `dsx-connect-<core_version>/`

- `docker-compose-dsx-connect-all-services.yaml` — API, Redis, Celery workers, optional rsyslog profile, SSE dependencies.
- `docker-compose-dsxa.yaml` — optional DSXA scanner for local malware verdicts.
- `.sample.core.env` — sample env file to pin image tags and set optional auth/DSXA settings.

## Prerequisites
- Docker Desktop / Docker Engine with the Compose plugin.
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- A shared Docker network created once: `docker network create dsx-connect-network` (all compose files use it).

## Architecture & Components

For the full diagrams see [Overview](../../overview.md). At a glance:

- **dsx_connect_api**: FastAPI app on port 8586 (REST + SSE + dashboard).
- **Redis**: queue broker + cache + pub/sub.
- **Celery workers**: scan_request, verdict_action, results, notification.
- **Log collector**: rsyslog profile (optional, defaults to stdout only).
- **DSXA scanner**: malware analysis engine (optional compose file).

![DSX-Connect Architecture](../../assets/dsx-connect-design.svg)

All worker communication flows through Redis queues. Scan requests enter `scan_request_queue`, DSXA handles scanning, verdicts/actions are enqueued, results are persisted/published, and SSE keeps the UI in sync.

## Core vs Connector Env

| Core Env (common) | Description |
| --- | --- |
| `DSXCONNECT_REDIS_URL` / `DSXCONNECT_TASKQUEUE__*` | Queue broker + backend URLs (defaults: `redis://redis:6379/0`). |
| `DSXCONNECT_RESULTS_DB` / `DSXCONNECT_RESULTS_DB__RETAIN` | Results DB backend + retention. Use Redis for demos or set to in-memory for ephemeral use. |
| `DSXCONNECT_USE_TLS`, `DSXCONNECT_TLS_CERTFILE`, `DSXCONNECT_TLS_KEYFILE` | Enable HTTPS on the API (see TLS section). |
| `DSXCONNECT_SCANNER__SCAN_BINARY_URL` | Endpoint for DSXA (`http://dsxa_scanner:5000/scan/binary/v2` when using the companion compose file). |

## TLS Options

See [Deploying with SSL/TLS](./tls.md) for Docker Compose specifics (dev cert generation, runtime mounts, and client trust).

## Component Details

### dsx_connect_api (FastAPI)
- REST API, SSE stream, UI dashboard, job management.
- Health check: `GET /dsx-connect/api/v1/healthz`.
- Dependencies: Redis (queues + SSE pub/sub).

### Redis
- Task broker + cache.
- Keyspace notifications enabled for SSE broadcasts.
- Lives on the compose network as `redis`.

### Celery Workers

| Worker | Queue | Default concurrency | Responsibilities |
| --- | --- | --- | --- |
| `dsx_connect_scan_request_worker` | `scan_request_queue` | 2 | Fetch files from connectors, submit to DSXA, enqueue verdicts. IO-bound; scale this first. |
| `dsx_connect_verdict_action_worker` | `verdict_action_queue` | 1 | Execute post-scan actions (delete/move/tag). Calls back into connectors. |
| `dsx_connect_results_worker` | `scan_result_queue` | 1 | Persist results, update stats, forward to syslog. |
| `dsx_connect_notification_worker` | `scan_result_notification_queue` | 1 | Publish events via Redis pub/sub, SSE, optional webhooks. |

Worker commands follow `celery -A dsx_connect.celery_app.celery_app worker --loglevel=warning -Q <queue> --concurrency=<n>`. Increase `--concurrency` or scale the service to parallelize.

### Log Collector (rsyslog)
- Enable the `rsyslog` profile to collect events; it writes to stdout for easy `docker logs`.
- dsx_connect_results_worker sends JSON events to `syslog:514` by default. Override `DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL`/`PORT` to point at an external collector or leave unset to disable.

### DSXA Scanner (Optional)
- Bring up via `docker compose --env-file dsx-connect-<core_version>/.core.env -f dsx-connect-<core_version>/docker-compose-dsxa.yaml up -d`.
- The scan request worker hits DSXA at `http://dsxa_scanner:5000/scan/binary/v2`.
- Can swap with a remote DSXA URL without changing compose; just override `DSXCONNECT_SCANNER__SCAN_BINARY_URL`.

## Deployment via Docker Compose

### Env file and pinned image tags
- Copy the sample env and pin tags:  
  ```bash
  cp dsx-connect-<core_version>/.sample.core.env dsx-connect-<core_version>/.core.env
  # edit dsx-connect-<core_version>/.core.env to set DSXCONNECT_IMAGE=dsxconnect/dsx-connect:<release-tag>
  # and optional DSXA/auth settings (APPLIANCE_URL/TOKEN/SCANNER_ID, DSXA_IMAGE, HOST_PORT, etc.)
  ```
- Use `--env-file` to point Compose at your `.core.env`; `docker-compose-dsx-connect-all-services.yaml` uses `DSXCONNECT_IMAGE` for the core image.

1. **Create shared network (once)**  
   ```bash
   docker network create dsx-connect-network --driver bridge
   ```
2. **Start DSXA scanner (optional)**
    If you want to use a DSXA scanner deployed within the same Docker host, use this. If you have an existing DSXA scanner, set `DSXCONNECT_SCANNER__SCAN_BINARY_URL` to point at it.
   ```bash
   docker compose --env-file dsx-connect-<core_version>/.core.env \
     -f dsx-connect-<core_version>/docker-compose-dsxa.yaml up -d
   ```
3. **Start dsx-connect stack**  
   ```bash
   docker compose --env-file dsx-connect-<core_version>/.core.env \
     -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml up -d
   ```
   Expected output (example):
   ```
   [+] Running 8/8
   ✔ Network dsx-connect-network                Created
   ✔ Container dsx-connect-redis-1              Started
   ✔ Container dsx-connect-rsyslog-1            Started
   ✔ Container dsx-connect-dsx_connect_api-1    Started
   ✔ Container dsx-connect-scan_request_worker-1 Started
   ✔ Container dsx-connect-verdict_action_worker-1 Started
   ✔ Container dsx-connect-results_worker-1     Started
   ✔ Container dsx-connect-notification_worker-1 Started
   ```
4. **Verify**  
   - API: http://localhost:8586  
   - `docker compose --env-file dsx-connect-<core_version>/.core.env -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml ps` to confirm healthy containers.  
   - Logs: `docker compose -f ... logs -f dsx_connect_api`
5. **Stop**  
   ```bash
   docker compose --env-file dsx-connect-<core_version>/.core.env \
     -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml down
   ```


## Authentication
- Docker Compose deployments intentionally run with connector auth disabled (no enrollment tokens, connectors unauthenticated). This keeps local demos simple.
- For production-grade deployments with enrollment + DSX-HMAC enforced, use the Helm charts (`dsx_connect/deploy/helm`) where secrets and toggles are managed securely.

## Common Troubleshooting

| Symptom | Fix |
| --- | --- |
| Port 8586 already in use | Edit compose file to remap API port or stop the conflicting service. |
| Workers stuck waiting for Redis | Ensure Redis health check passes; look at `docker logs dsx-connect-redis-1`. |
| SSE clients disconnecting | API has a 30s graceful shutdown window; ensure you stop the stack with `docker compose down` to let SSE flush. |
| Syslog not receiving events | Start the stack with the `rsyslog` profile, or point `DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL` at your collector. |
| Need persistent Redis | Mount a volume to `/data` in the Redis service. |
| Large backlogs | Scale `dsx_connect_scan_request_worker` (and connectors/DSXA) to increase throughput. |
