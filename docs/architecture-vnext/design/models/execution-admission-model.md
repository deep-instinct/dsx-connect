# Execution Admission and Scan Dispatch Gate Model

## Purpose

This document defines the higher-level control plane for whether accepted execution work should be released into scan processing.

The goal is to prevent DSX-Connect from continuing to fan out known-doomed scan work when scanner or reader infrastructure is unhealthy, while still preserving authoritative acceptance where appropriate.

---

## Core Principle

Acceptance is not the same thing as scan dispatch.

DSX-Connect should be able to:

- accept and persist batch intent
- hold scan dispatch temporarily
- later resume dispatch when health recovers

without forcing scan workers to become system-wide admission controllers.

---

## Why This Exists

Worker-local retry and terminal-error handling are necessary but insufficient.

They answer:

- should this item retry?
- should this item fail terminally?

They do not answer:

- should we continue releasing new scan work right now?
- should we hold scan dispatch for one integration?
- should we reject or hold newly submitted batches?

Those are higher-level execution-admission questions.

---

## Scope of Control

The first control surface should focus on **scan dispatch**, because scan is the earliest expensive external dependency and the main fan-out point.

This model intentionally does not try to gate:

- remediation
- DIANNA
- result-sink emission

Those may eventually need health-aware admission too, but they should not be coupled to scan-dispatch control initially.

---

## Decision Layers

### 1. Batch Admission

Should a new batch request be accepted?

Possible actions:

- `accept_and_dispatch`
- `accept_and_hold`
- `reject`

This is the connector-facing and API-facing decision.

### 2. Scan Dispatch

For accepted items, should `scan.requested` work be published now?

Possible actions:

- `dispatch`
- `hold`

This is the internal work-release decision.

---

## Health Scope

The model should support scoped health signals.

### Global

Examples:

- DSXA auth/config is invalid
- DSXA is unavailable system-wide

Effect:

- all scan dispatch may be held

### Integration

Examples:

- one integration's proxy reader config is invalid
- one integration's connector endpoint is failing

Effect:

- only that integration's scan dispatch is held

Future scopes may include:

- scanner provider
- reader strategy
- connector endpoint

---

## Health Classification

Raw failure counts are not enough.

The gate should respond to **classified signals**, such as:

- `scanner_auth_invalid`
- `scanner_unreachable`
- `scanner_timeout_threshold_exceeded`
- `reader_config_invalid`
- `connector_proxy_unreachable`

This prevents one item-level terminal failure, such as a missing file, from incorrectly pausing unrelated work.

---

## Suggested State Model

### Admission Action

```text
accept_and_dispatch
accept_and_hold
reject
```

### Dispatch Gate Action

```text
dispatch
hold
```

### Scope

```text
global
integration
```

### Gate Status

Suggested fields:

- `subsystem`
- `scope`
- `scope_id`
- `admission_action`
- `dispatch_action`
- `reason`
- `details`
- `updated_at`

---

## Examples

### Example 1: Global DSXA Auth Failure

- health signal:
  - `scanner_auth_invalid`
- scope:
  - `global`
- admission:
  - `accept_and_hold`
- dispatch:
  - `hold`

Result:

- new batches may still be accepted and counted
- no new `scan.requested` items are released
- operators can recover credentials and resume later

### Example 2: One Integration Proxy Reader Misconfigured

- health signal:
  - `reader_config_invalid`
- scope:
  - `integration`
- `scope_id`:
  - `filesystem-local`
- admission:
  - `accept_and_hold`
- dispatch:
  - `hold`

Result:

- only that integration's scan dispatch is held
- other integrations continue normally

### Example 3: Missing File for One Item

- health signal:
  - none at subsystem level
- worker result:
  - terminal item failure

Result:

- the item fails terminally
- no global or integration pause is triggered

---

## Persistence / Release Direction

The preferred initial behavior is:

1. accept batch and item records as usual
2. if dispatch is held, do not publish `scan.requested` yet
3. represent the held state explicitly
4. resume by releasing held scan work later

Implementation options:

- held item state on `job_item`
- held publish state in outbox
- explicit deferred-dispatch records

The architecture does not yet require choosing one immediately, but it should avoid hiding held work in ad hoc worker logic.

---

## Relationship to DLQ

DLQ replay and scan-dispatch gating are related but separate concerns.

- dispatch gate:
  - controls release of new scan work
- DLQ replay:
  - controls replay of previously failed work

Both should eventually have operator surfaces, but dispatch gating should come first because it prevents avoidable churn.

---

## API / Status Direction

Read-only visibility should come before operator controls.

Suggested surfaces:

- execution status
- execution topology
- future admission status endpoint

What those surfaces should show:

- current gate status
- scope
- reason
- current policy defaults

What they should not yet do:

- pause/resume by API
- replay DLQs
- inspect broker message bodies

---

## Implementation Recommendation

Implement in this order:

1. typed admission/gate models
2. read-only status exposure
3. gate evaluation component
4. deferred scan publish behavior
5. operator pause/resume controls

This keeps the system explainable and avoids embedding health-based flow control into scan workers themselves.
