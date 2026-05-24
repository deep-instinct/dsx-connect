# Post-Scan Orchestration Model

## Purpose

This document defines what happens **after scan completion** in DSX-Connect.

The goal is to keep responsibilities narrow:

- scan execution stays in the scan worker
- policy stays a distinct decision component
- external side effects stay in isolated workers
- result emission happens per stage, not as one monolithic final blob
- content preservation and reuse stay behind the Reader abstraction

---

## Core Principles

### Stage Boundary Is Not the Same as Worker Boundary

DSX-Connect should keep explicit workflow stages:

- `scan_stage`
- `policy_stage`
- `remediation_stage`
- `dianna_stage`
- `delivery_stage`

But not every stage must be implemented as a separate queue hop or dedicated deployed worker.

The system should preserve:

- explicit state
- explicit auditability
- explicit typed results

without creating unnecessary runtime fragmentation.

### Cheap Decisions Stay Close to Their Trigger

Policy evaluation after scan is typically:

- deterministic
- fast
- based on scan result + integration/scope/config context
- non-side-effecting

That means policy may remain a distinct **component** without necessarily requiring a distinct **worker**.

### External Side Effects Stay Isolated

Operations that mutate or depend on systems outside core should remain isolated:

- remediation
- DIANNA analysis
- result delivery

These are appropriate worker boundaries because they involve:

- network I/O
- retries
- unpredictable latency
- side effects outside DSX-Connect control

---

## Post-Scan Handoff

The preferred model is:

1. scan worker reads content through a Reader
2. scan worker submits content to DSXA
3. scan worker produces a normalized `ScanResult`
4. scan worker hands the result to a policy component
5. policy component returns a structured orchestration decision
6. scan worker persists `policy_stage`
7. scan worker enqueues only the follow-on work that is actually required

This preserves concurrency without introducing a central master orchestrator.

---

## Component Responsibilities

### Scan Worker

Owns:

- content acquisition through Readers
- scan execution
- scan-stage persistence
- policy handoff invocation
- thin follow-on enqueueing based on policy output

Does not own:

- repository-specific read logic
- large `if/elif` orchestration trees
- repository remediation logic
- DIANNA execution logic
- result aggregation into one final output blob
- special-case content caching policy

### Policy Component

Owns:

- interpreting normalized scan results
- applying policy/config/scope context
- deciding which stages should run
- deciding which stages should be explicitly skipped
- deciding what result families should be delivered
- deciding whether content should be preserved for later stages

Does not own:

- queue consumption as a required deployment boundary
- repository I/O
- remediation execution
- DIANNA execution
- delivery execution

### Remediation / DIANNA / Delivery / ResultSink Components

Own:

- external side-effect execution
- stage-local retry behavior
- stage-local typed result reporting

Do not own:

- global orchestration
- policy evaluation
- content preservation policy

---

## Policy Handoff Contract

The policy component should accept a normalized handoff request rather than raw DSXA or connector-specific payloads.

Suggested request fields:

- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `content_source`
- `scan_result`
- `delivery_requirements`
- normalized integration/scope policy context
- optional item metadata

Suggested response shape:

```json
{
  "policy_stage_result": {
    "policy_id": "default-scan-policy",
    "decision_trace": {
      "matched_rule": "deliver-benign-full-scan-results"
    }
  },
  "remediation": {
    "state": "skipped",
    "reason": "benign_verdict",
    "plan": null
  },
  "dianna": {
    "state": "skipped",
    "reason": "not_auto_requested",
    "details": {
      "verdict": "Benign"
    }
  },
  "delivery": {
    "request_now": true,
    "wait_for_dianna": false,
    "targets": [
      {
        "connector": "filesystem-local"
      }
    ]
  },
  "content_preservation": {
    "mode": "none",
    "reason": "no_later_stage_requires_content"
  },
  "result_delivery_policy": {
    "scan": "all_results",
    "remediation": "all_outcomes",
    "dianna": "completed_only"
  }
}
```

The exact schema may evolve, but these semantics should remain stable.

---

## Skip Semantics

`pending` means:

- stage has not yet been evaluated or requested

`skipped` means:

- stage was explicitly evaluated and determined not to apply in the automated flow

Examples:

- `remediation_stage.state = skipped`
  - `reason = benign_verdict`
  - `reason = below_policy_threshold`
  - `reason = no_remediation_plan`

- `dianna_stage.state = skipped`
  - `reason = not_auto_requested`
  - `details.verdict = Benign`

Manual or later explicit invocation may still reopen a skipped stage where the product allows it.

---

## Result Delivery Model

DSX-Connect should not force all results into one final combined output payload.

Instead, result emission should be stage-aware and incremental.

### Why

- DSXA is already the source of truth for malicious scanner events
- benign/full-scan reporting is still operationally useful
- remediation outcomes have their own timing and semantics
- DIANNA results have their own timing and semantics
- downstream systems such as SIEMs or analytics stores can recombine stage outputs later

### Result Families

The platform should treat the following as distinct delivery-worthy outputs:

- `scan_result`
- `remediation_result`
- `dianna_result`
- optional future `workflow_summary`

### Stage-Specific Emission Policy

Examples of policy-controlled delivery modes:

- scan:
  - `never`
  - `all_results`
  - `malicious_only`

- remediation:
  - `never`
  - `failures_only`
  - `all_outcomes`

- dianna:
  - `never`
  - `completed_only`
  - `all_outcomes`

Emission should happen when each result family becomes available, not only after every possible stage has finished.

---

## ResultSink Direction

DSX-Connect should emit normalized JSON result events to a **ResultSink** abstraction.

The ResultSink is responsible for:

- accepting normalized result events from core
- writing them to a local sink or adapter
- optionally offering stronger guarantees for selected event families

The ResultSink is not inherently responsible for:

- final destination-specific forwarding policy
- becoming the authoritative workflow state owner

### Exemplar Deployment Pattern

The reference operational pattern is:

1. DSX-Connect emits JSON result events to a local ResultSink
2. `rsyslog` ingests those events
3. `rsyslog` decides whether and where to forward them

This keeps forwarding/routing outside the core orchestration engine while preserving normalized stage-specific events.

### Result Families for ResultSink Emission

The ResultSink should receive events such as:

- `scan_result`
- `remediation_result`
- `dianna_result`
- optional `workflow_summary`

### Stronger-Guarantee Exception

Most result events are operational conveniences.

If a specific family such as DIANNA requires higher delivery guarantees, that should be implemented through:

- a stronger ResultSink implementation
- or an agent-backed durable forwarding path

not by making all core result emission destination-aware.

### Correlation

Separate results should be recombinable later using identifiers such as:

- `job_id`
- `job_item_id`
- `integration_id`
- `object_identity`
- `file_hash`
- `scan_guid`

This supports:

- SIEM correlation
- PostgreSQL queries across stages
- UI read models
- later analytics pipelines

---

## Content Preservation and Cached Reads

Policy may determine that later stages should reuse the same bytes rather than re-read the original repository object.

Examples:

- DIANNA needs the scanned file later
- remediation moved the original object
- a later validation step must inspect the preserved artifact

That decision should update normalized content-source state, for example:

- `original`
- `cached`
- `quarantine`
- `none`

The follow-on worker should then resolve a Reader again.

It should not:

- know where the scan worker placed temp files
- require scan-worker-owned cache logic
- embed repository-specific reread behavior

### Stub Direction

Future Reader implementations may include:

- `CachedArtifactReader`
- `QuarantineReader`

These should be resolved through the same Reader selection mechanism as `proxy` and `native`.

---

## Recommended Runtime Shape

Near-term preferred runtime shape:

- scan worker
  - scan execution
  - policy handoff
  - enqueue downstream work

- remediation worker
  - isolated repository mutation / side effects

- dianna worker
  - isolated external analysis flow

- result sink emitter
  - emits normalized JSON events
  - does not own general forwarding policy

This keeps the common path fast while preserving isolation where it matters.

---

## Non-Goals

This document does not define:

- policy rule syntax in detail
- remediation action schemas in detail
- DIANNA protocol specifics
- final cache storage implementation
- a mandatory single summary event format

---

## Open Questions

- Should policy handoff be a direct in-process call, a library interface, or an internal service boundary?
- Should a compact workflow-summary event exist in addition to stage-specific outputs?
- How long should cached artifacts live when preserved for later stages?
- Which later stages are allowed to transition `content_source` from `original` to `cached` or `quarantine`?
