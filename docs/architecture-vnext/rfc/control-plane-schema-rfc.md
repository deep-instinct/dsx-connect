# PostgreSQL Control-Plane Schema RFC

This document defines the initial PostgreSQL schema for DSX-Connect control-plane state and domain-job durability.

SQL source:

- `dsx_connect/database/sql/control_plane_schema.sql`

## Goals

- Make PostgreSQL the source of truth for integrations, scopes, coverage, jobs, and idempotency.
- Support one-active-full-scan-per-scope as a DB-level invariant.
- Provide durable job ledger semantics independent of broker restarts.

## Tables

### `cp_integrations`

Platform integration roots (tenant/account/project level).

- identity and platform key
- enabled flag
- integration config payload

### `cp_scopes`

Protected scopes owned by core.

- `scope_type`: `path|identity`
- `resource_selector`: stable identity or path/prefix
- `filter_expression`
- `mode`: `monitor|full_scan`
- `post_scan_policy_json` for outcome policy mapping

### `cp_coverage_rules`
### `cp_coverage_exclusions`

Coverage-mode configuration:

- protect all containers of kind
- explicit exclusions list

### `cp_full_scan_jobs`

Scope-owned full scans with progress counters and checkpoints.

Critical invariant:

- partial unique index enforces one active full scan per scope (`queued|running`).

### `cp_jobs`

Canonical domain job ledger.

- envelope fields (`job_type`, `state`, correlation lineage)
- scope/full-scan/object links
- idempotency key
- outcome + reason
- payload/error json
- lifecycle timestamps

### `cp_idempotency_keys`

Optional explicit idempotency ledger (in addition to `cp_jobs.idempotency_key` uniqueness).

### `cp_outbox_events`

Transactional outbox for reliable notifications/webhooks/SSE fanout from durable state transitions.

## Canonical Job Envelope (v1)

Canonical model is defined in:

- [job_models.py](/Users/logangilbert/PycharmProjects/dsx-connect/shared/models/job_models.py)

Key fields:

- `job_id`, `job_type`, `state`
- `integration_id`, `scope_id`, `object_identity`
- `parent_job_id`, `root_job_id`, `correlation_id`
- `source_type`, `source_entity_id`
- `idempotency_key`, `attempt`, `max_attempts`
- `outcome`, `outcome_reason`
- `payload`
- lifecycle timestamps

## Queue/Broker Relationship

- RabbitMQ = transport + redelivery.
- PostgreSQL = authoritative state + idempotency + audit.
- Workers should ack broker messages only after durable state transition is committed.

## Notes

- This schema is additive and intended for staged rollout.
- Existing Redis-backed paths remain operational during migration.
- Apply this schema behind feature flags before switching production execution to DB-backed orchestration.

## Dev Preview Enablement

Preview mirror is optional and best-effort. Current gates:

- `DSXCONNECT_FEATURES__ENABLE_SCOPE_ENGINE_PREVIEW=true`
- `DSXCONNECT_FEATURES__ENABLE_JOB_MODEL_PREVIEW=true`
- `DSXCONNECT_FEATURES__ENABLE_PREVIEW_POSTGRES_MIRROR=true`

Database settings:

- `DSXCONNECT_CONTROL_PLANE_DB_URL=postgresql://...`
- `DSXCONNECT_CONTROL_PLANE_DATABASE__AUTO_APPLY_SCHEMA=true` (optional in local dev)

If PostgreSQL is unavailable (or `psycopg` is not installed), preview APIs still function in-memory and log mirror failures.

## Local Testing (Docker PostgreSQL)

Start a local Postgres:

```bash
docker run --name dsxcp-pg \
  -e POSTGRES_USER=dsx \
  -e POSTGRES_PASSWORD=dsx \
  -e POSTGRES_DB=dsx_connect \
  -p 5432:5432 \
  -d postgres:16
```

Install dependencies (includes `psycopg[binary]`):

```bash
pip install -r dsx_connect/requirements.txt
```

Set env for preview mirror:

```bash
export DSXCONNECT_FEATURES__ENABLE_SCOPE_ENGINE_PREVIEW=true
export DSXCONNECT_FEATURES__ENABLE_JOB_MODEL_PREVIEW=true
export DSXCONNECT_FEATURES__ENABLE_PREVIEW_POSTGRES_MIRROR=true
export DSXCONNECT_CONTROL_PLANE_DB_URL=postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect
export DSXCONNECT_CONTROL_PLANE_DATABASE__AUTO_APPLY_SCHEMA=true
```

Then start DSX-Connect and use the Dev Architecture Preview panel in the web UI.  
You should see `postgres_mirror_attached: true` in:

- `/dsx-connect/api/v1/scope-engine/preview`
- `/dsx-connect/api/v1/job-model/preview`

And explicit mirror DB health via:

- `/dsx-connect/api/v1/job-model/preview/mirror-health`

Read back mirrored rows:

- `/dsx-connect/api/v1/scope-engine/preview/scopes?source=postgres&limit=200`
- `/dsx-connect/api/v1/job-model/preview/jobs?source=postgres&limit=200`

Default source remains `memory`.
