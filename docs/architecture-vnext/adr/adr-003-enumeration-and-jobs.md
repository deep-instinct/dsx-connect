# ADR-003: Enumeration, Batching, and Job Ownership Model

## Status

Proposed

## Context

Current patterns show:

* Connectors enumerate items and submit work asynchronously
* Counting is inconsistent (discovered vs accepted vs processed)
* Connectors may overproduce or miscount
* Tight coupling between enumeration and job tracking

We want:

* Clear ownership of job state
* Accurate counting
* Scalable ingestion
* Decoupling of connectors from orchestration logic

---

## Decision

Adopt a **batch + cursor enumeration model**, with **core-owned job state**.

---

## Model

### Connector Responsibilities

* Return:

    * Batch of items (N items)
    * Cursor for continuation

* Each item includes:

    * Stable identifier
    * Minimal metadata
    * Optional fetch locator

* Connectors do NOT:

    * Track counts
    * Assume acceptance
    * Enforce policy

---

### Core Responsibilities

* Requests batches from connectors
* Persists accepted items into queue
* Owns all job state and counting

---

## Counting Model

* discovered_count:

    * Optional
    * Advisory only

* accepted_count:

    * Incremented only when core accepts work

* processed_count:

    * Incremented on completion

* expected_total:

    * Only set when known with certainty

---

## Consequences

### Positive

* Accurate, authoritative counts
* Clear separation of concerns
* Better backpressure handling
* Scales with large datasets

### Tradeoffs

* Requires new connector contract
* Cursor design must be consistent
* Core becomes more complex

---

## Open Questions

* What is the batch size strategy?
* How do we handle retries/idempotency?
* Do we support streaming vs batch modes?
* How are partial failures handled?

---

## Notes

* This aligns with a queue-based architecture (potentially RabbitMQ or similar)
* Supports future high-scale scanning models
