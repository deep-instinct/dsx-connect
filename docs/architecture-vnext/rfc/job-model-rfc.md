# Job Model RFC

This RFC defines a non-breaking target model for domain-specific jobs and worker roles in DSX-Connect, aligned with the integration/scope/policy architecture.

## Goals

- Replace generic async task semantics with domain job semantics.
- Keep connectors as thin adapters.
- Keep policy/orchestration in core.
- Improve auditability, retries, ownership, and observability.
- Support scale by separating worker roles.

## Core Principle

- Jobs represent business operations.
- Workers represent execution roles.
- PostgreSQL stores durable control-plane and job state.
- RabbitMQ carries domain job messages.

## Worker Roles

### 1. Monitor / Connector Ingest Worker

Consumes `MonitorEventIngestJob`:

- Validate normalized connector event payload.
- Perform transport-level dedupe if required.
- Forward normalized context to core policy logic.
- Emit downstream scan jobs only when object qualifies.

### 2. Full Scan Enumeration Worker

Consumes `FullScanScopeJob`, `EnumerateScopePageJob`:

- Enumerate scope incrementally at scan-time live state.
- Continue via pagination jobs.
- Emit object scan jobs for discovered files/attachments.
- Update full-scan progress context.

### 3. Scan Request Worker

Consumes `ScanObjectJob`:

- Fetch object from source.
- Submit to DSXA.
- Emit finalization job with verdict payload.

### 4. Results / Finalization Worker

Consumes `FinalizeScanObjectJob`:

- Persist scan result.
- Normalize raw scan/platform result into canonical scan outcome.
- Update object status and full-scan counters.
- Write audit trail.
- Evaluate post-scan outcome policy.
- Decide whether remediation/notification/retry jobs are required.

### 5. Remediation Worker

Consumes `ApplyRemediationJob`:

- Execute policy-selected action (delete/move/tag/quarantine/etc.).

### 6. Notification Worker

Consumes `SendNotificationJob`:

- Deliver SSE/UI updates, webhooks, email, and future channels.

## Domain Jobs

### `MonitorEventIngestJob`

- integration ID
- normalized resource identity
- event metadata/timestamp
- optional raw connector metadata

### `FullScanScopeJob`

- full scan job ID
- scope ID
- integration ID
- requested by
- options

### `EnumerateScopePageJob`

- full scan job ID
- scope ID
- continuation token/cursor

### `ScanObjectJob`

- object identity
- scope ID
- integration ID
- source reason (`monitoring | full_scan | manual`)
- parent context (including attachment parent when applicable)

### `FinalizeScanObjectJob`

- scan object job ID
- raw verdict/result payload
- normalized outcome classification
- object/scope context
- optional parent full-scan job ID

### `ApplyRemediationJob`

- object identity
- scope ID
- selected action
- audit context

### `ScheduleRetryJob` (optional future extension)

- source job ID
- retry reason/outcome
- attempt index / next-at
- scope/object context

### `SendNotificationJob`

- event type
- target channels/audience
- object/scope/job context
- rendered payload inputs

## Monitoring Flow

1. Connector emits normalized `MonitorEventIngestJob`.
2. Ingest worker validates and forwards for policy match.
3. Core resolves scope (exactly one), exclusions, and filters.
4. If qualified, core emits `ScanObjectJob`.
5. Scan worker emits `FinalizeScanObjectJob`.
6. Finalization normalizes outcome and emits remediation/notification/retry jobs as needed.

## Full Scan Flow

1. User requests full scan for a scope.
2. Core enforces one active full scan per scope.
3. Core emits `FullScanScopeJob`.
4. Enumeration worker emits `EnumerateScopePageJob` and `ScanObjectJob`.
5. Scan worker emits `FinalizeScanObjectJob`.
6. Finalization updates full-scan counters/completion and evaluates outcome policy.
7. Optional remediation/notification follows normal path.

## Full Scan Rules

- One active full scan per scope.
- Scope-specific progress/stats/checkpoints.
- Live dataset semantics (not frozen snapshot).
- If a second request arrives while active, return active job metadata.

## Why This Model

- Clear ownership per operation.
- Better scaling by role-specific worker pools.
- Better troubleshooting through domain-level job traces.
- Cleaner persistence for control plane and audits.

## Outcome Policy (Post-Scan Policy)

Remediation is not modeled as "if malicious then action". It is modeled as:

- normalize outcome
- evaluate policy for that outcome
- emit zero or one remediation job
- emit zero or more side-effect jobs (notification/retry)

Example policy shape:

```json
{
  "actions": {
    "clean": { "remediation": "none", "notify": false },
    "malicious": { "remediation": "quarantine", "notify": true },
    "unable_to_scan": { "remediation": "move", "notify": true },
    "fetch_failed": { "remediation": "none", "notify": true },
    "timeout": { "retry": true, "notify": false },
    "unsupported_type": { "remediation": "none", "notify": false }
  }
}
```

This keeps the finalization worker as the decision engine and remediation worker as pure side-effect execution.

## Non-Breaking Preview Path

An in-memory, feature-flagged preview API can be used to validate this model before wiring production queues and persistence:

- `DSXCONNECT_FEATURES__ENABLE_JOB_MODEL_PREVIEW=true`
- Preview endpoints under `/dsx-connect/api/v1/job-model/preview/*`

Optional write-through mirror to PostgreSQL during preview:

- `DSXCONNECT_FEATURES__ENABLE_PREVIEW_POSTGRES_MIRROR=true`
- `DSXCONNECT_CONTROL_PLANE_DB_URL=postgresql://...`

Preview mode does not affect existing scan routing.
