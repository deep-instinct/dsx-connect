# ADR-012: Gate Scan Dispatch Above Workers, Using Health-Scoped Admission

- **Status:** Proposed
- **Date:** 2026-05-22
- **Decision Owners:** DSX-Connect Architecture
- **Related:** ADR-003 (Enumeration and Jobs), ADR-007 (Reader Contract), ADR-011 (ResultSink)

## Context

DSX-Connect now has stronger item-level semantics for scan execution:

- scan workers classify failures as terminal vs retryable
- RabbitMQ owns bounded retry and DLQ handling
- batch jobs and job items are persisted explicitly in core

That solves worker-local retry behavior, but it does not answer a higher-level operational question:

What should core do when the scan subsystem is unhealthy in a way that makes continued item fan-out undesirable?

Examples:

- DSXA credentials are invalid globally
- the scanner service is unavailable above a sustained threshold
- one integration's proxy reader is misconfigured
- one integration's connector read path is unreachable

In these situations, continuing to break accepted batches into `scan.requested` work may create large volumes of doomed item attempts, even if individual workers classify failures correctly.

At the same time, rejecting all incoming batch requests is often too aggressive:

- connectors may still need to hand work to core
- core may still want authoritative acceptance and counting
- operators may prefer to hold accepted work until scan health recovers

The architecture needs a control point above workers that can:

- continue accepting work
- optionally pause scan dispatch
- scope that pause globally or per integration
- later resume without rewriting worker semantics

## Decision

DSX-Connect will treat **scan dispatch** as a higher-level gated action, separate from:

- batch acceptance
- item persistence
- worker-local terminal/retryable classification

The preferred control model is:

1. core may continue accepting batch requests and persisting parent/item intent
2. scan item fan-out is gated by execution admission policy
3. health classification determines whether dispatch is:
   - allowed
   - held
   - rejected
4. workers remain responsible only for item-level execution outcomes

## Decision Drivers

- preserve authoritative acceptance even during temporary downstream instability
- prevent large volumes of known-doomed scan work from being enqueued
- keep worker responsibilities narrow
- separate item-level failure semantics from subsystem health semantics
- support scoped pause behavior such as:
  - global
  - integration-specific
  - future scanner/provider-specific

## Clarifying Principle

Terminal item failure is not the same as subsystem unhealthiness.

Examples:

- file missing
  - terminal for one item
  - does not justify global pause
- invalid DSXA authentication
  - global scanner health issue
  - may justify holding scan dispatch globally
- invalid connector proxy configuration for one integration
  - integration-scoped health issue
  - may justify holding scan dispatch only for that integration

Core should therefore react to **classified health signals**, not raw terminal error counts alone.

## Admission / Dispatch Split

The architecture should distinguish:

### Ingestion / Admission

Should core accept a new batch request at all?

Possible behaviors:

- `accept_and_dispatch`
- `accept_and_hold`
- `reject`

### Work Release / Scan Dispatch

For accepted items, should core publish `scan.requested` work now?

Possible behaviors:

- publish immediately
- hold pending health recovery
- hold for one integration only

This means a batch can be accepted without necessarily releasing all item-level scan work immediately.

## Health Scope

The model should support at least:

- `global`
- `integration`

Future extensions may include:

- `scanner_provider`
- `reader_strategy`
- `connector_endpoint`

## Operational Consequences

As a result of this decision:

- scan workers should not own system-wide pause logic
- execution/control-plane surfaces should expose admission / dispatch health state
- batch requests may remain accepted while scan dispatch is paused
- queued work should be resumable without reconstructing accepted batches
- DLQ replay remains a separate later concern

## Initial Design Direction

The first implementation step should be read-only and declarative:

1. model admission / dispatch state explicitly
2. expose configured / current gate state through status APIs
3. define health signal classifications
4. delay actual gating behavior until the contract is clear

## Follow-On Work

1. define execution admission and scan-dispatch-gate models
2. define health signal input classification
3. expose read-only gate state in execution status surfaces
4. decide whether held items are represented by:
   - job state
   - outbox state
   - deferred publish records
5. define resume behavior for held scan work
6. later, define operator controls for pause/resume

## Summary

DSX-Connect should not rely on scan workers alone to protect the system from unhealthy scan infrastructure.

Core should separate:

- acceptance
- scan dispatch
- worker execution

and use health-scoped admission/gating above workers to decide when accepted work should be released into scan processing.
