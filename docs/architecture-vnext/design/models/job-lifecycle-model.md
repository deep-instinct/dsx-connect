# Job Lifecycle Model

## Purpose

This document defines the lifecycle of scan-related jobs in DSX-Connect and clarifies ownership of job state.

---

## Core Principle

Core owns job state.

Connectors may discover or supply work, but they do not authoritatively own:

- acceptance
- processing state
- terminal counts
- workflow completion

---

## Job Types

Likely job families include:

- enumerate scope
- ingest object
- fetch object
- scan object
- apply decision
- remediate object
- notify/report
- manual review workflow steps

Not every flow requires every job type.

---

## Lifecycle Stages

### 1. Discovered
An object is seen by enumeration or event monitoring.

This is advisory, not authoritative proof that work was accepted.

### 2. Accepted
Core accepts the work item and persists it to its job system.

This is the first authoritative counting point.

### 3. In Progress
A worker has started processing the job.

### 4. Terminal
The job reaches a terminal outcome, such as:
- completed
- failed
- skipped
- canceled

### 5. Post-Decision Workflow
Optional follow-on actions:
- remediation
- notification
- hold queue
- manual review

---

## Counting Semantics

### discovered_count
Optional and advisory.

### accepted_count
Authoritative. Increment only when core persists accepted work.

### processed_count
Authoritative. Increment when processing reaches terminal state.

### expected_total
Only set when actually known.

---

## Why This Matters

This prevents common failure modes:

- connector says work was “counted” before it was accepted
- async submission diverges from persisted job state
- each connector counts differently
- reporting becomes unreliable

---

## Relationship to Enumeration

Enumeration should provide batches and cursors.
Core should accept items from those batches and create the relevant jobs.

This cleanly separates:
- discovery
- acceptance
- processing
- reporting

---

## Open Questions

- What are the canonical job types in v1?
- Do we model parent/child job relationships explicitly?
- How are retries represented?
- Where does idempotency live?
- How are manual review states represented in the lifecycle?

---

## Current Direction

DSX-Connect should move toward:
- batch/cursor enumeration
- core-owned acceptance
- core-owned lifecycle state
- explicit terminal semantics