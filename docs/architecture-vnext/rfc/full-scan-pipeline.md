# Full Scan Pipeline (Unified Job Model)

This document records the agreed full-scan model for DSX-Connect under the new control-plane architecture.

## Mental Model

A full scan is a controlled enumeration of a protected scope that generates `ScanObjectJob` units into the same pipeline used by monitoring.

- Monitoring = real-time event stream
- Full scan = generated event stream
- Both flow through the same core policy + scan + finalize + action pipeline

Full scan is not a separate scanning subsystem.

## High-Level Flow

```text
User -> FullScanScopeJob -> Enumeration -> ScanObjectJobs -> Scan -> Finalize -> (Remediate -> Notify)
```

## 1. Full Scan Request

When user requests full scan for `scope_id`:

1. Core checks active full scan for that scope.
2. If active:
   - return existing `job_id`, status, and progress
   - do not silently queue another active full scan
3. If not active:
   - create durable full-scan job record
   - emit `FullScanScopeJob`

Rule: one active full scan per scope.

## 2. Enumeration Start

Enumeration worker consumes `FullScanScopeJob` and enumerates from scope root.

Rule: enumerate from scope root, not integration root.

## 3. Pagination

Connector returns page + cursor. For each page:

- emit `ScanObjectJob` per discovered object
- if cursor exists, emit `EnumerateScopePageJob`

This provides resumability and bounded memory behavior.

## 4. ScanObjectJob Shape

Each discovered object becomes a scan job with:

- `object_identity`
- `scope_id`
- `integration_id`
- source context:
  - `source_type=full_scan`
  - `source_entity_id=<full_scan_job_id>`

Idempotency and dedupe apply.

## 5. Scan Execution

Scan worker consumes `ScanObjectJob`:

1. fetch object/attachment
2. submit to DSXA
3. receive verdict
4. emit `FinalizeScanObjectJob`

## 6. Finalization

Finalization worker consumes `FinalizeScanObjectJob`:

- persist result
- normalize to canonical outcome
- update object status
- update full-scan counters
- write audit trail

If policy requires:

- emit `ApplyRemediationJob`
- emit `SendNotificationJob`

## 7. Progress Semantics

Progress is based on finalized objects, not enumeration progress alone.

Why:

- enumerated != scanned
- scanned != finalized

Operational progress should reflect finalized units.

## 8. Completion Criteria

Full scan is `completed` only when:

1. enumeration is exhausted (no more cursors/pages), and
2. all spawned scan jobs for that full scan are finalized

## Behavior Decisions

### Live Dataset

Full scan operates on live data at enumeration time.

- No point-in-time snapshot guarantee.
- Objects appearing later are expected to be handled by monitoring.

### No Snapshot Mode

Intentional tradeoff for simplicity and throughput.

### Idempotency Required

Object scan + finalize + side effects must be safe under retries/redelivery.

### Outcome-Based Policy

Post-scan policy evaluates normalized outcome, not only malicious verdict:

- clean
- malicious
- unable_to_scan (+ reason)
- fetch_failed
- timeout
- unsupported_type
- policy_blocked

### No Duplicate Policy Evaluation

No-overlap scope rule ensures deterministic scope ownership.

## Failure Model

### Connector/Enumeration Failure

- `EnumerateScopePageJob` retries
- cursor-based resume

### Worker Crash During Scan

- queue redelivery occurs
- idempotency prevents duplicate side effects

### Partial Completion

- job remains running with visible progress
- resume continues via pending jobs

### Cancellation

On cancel:

- mark full-scan job canceled
- stop scheduling new enumeration jobs
- policy determines whether in-flight jobs drain or are interrupted

## Throughput and Scaling

Scale independently by worker role:

- enumeration workers
- scan workers
- finalization workers
- remediation workers
- notification workers

Primary bottlenecks remain:

- connector API limits
- object fetch throughput
- DSXA scan capacity

## Key Insight

Full scan is synthetic event generation. Monitoring is native event ingestion. Both feed one unified pipeline.

## Next Design Artifact

Define the canonical job envelope + message schema:

- correlation fields
- idempotency keys
- causality/parent references
- retry metadata
