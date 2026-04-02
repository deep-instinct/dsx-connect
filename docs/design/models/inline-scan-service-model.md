# Inline Scan Service Model (File Scanning as a Service)

## Purpose

This document defines how DSX-Connect provides **inline file scanning and decisioning** as a service to applications and platforms.

This model is the foundation of DSX-Connect as a **Security Hub**.

---

## Core Idea

Applications should not need to understand:

- DSXA
- connectors
- scanning workflows
- policy logic

Instead, they should call a single service:

> “Here is a file — tell me what to do with it.”

---

## High-Level Flow

1. Application receives a file (upload, API request, etc.)
2. Application sends file (or reference) to DSX-Connect
3. DSX-Connect:
    - scans via DSXA
    - evaluates policy
    - normalizes verdict
4. DSX-Connect returns a decision
5. Application enforces the decision

---

## Key Principle

DSX-Connect is a **decision point**, not a storage system.

- It does not need to own file persistence
- It determines whether a file is safe to store or process

---

## API Model

### Core Operation

**Scan + Decide (Synchronous)**

Input:
- file (stream or reference)
- context (tenant, application, optional metadata)

Output:
- normalized verdict
- decision (allow/block/quarantine/hold)
- reason / classification
- optional policy metadata

---

## Input Models

### 1. File Upload (Stream)

- Application sends file content directly
- Best for:
    - uploads
    - small to medium files
    - immediate decisions

---

### 2. File Reference

- Application sends a reference:
    - URL
    - object locator
    - connector-backed reference

- DSX-Connect retrieves file via connector or direct fetch

- Best for:
    - large files
    - existing repository content

---

### 3. Hybrid

- Initial metadata call → decision whether to fetch/scan
- Useful for optimization and cost control

---

## Decision Model

DSX-Connect returns normalized outcomes:

- allow
- block
- quarantine
- hold_for_review

Optional extensions:
- allow_with_warning
- allow_with_audit_flag
- skip (explicit policy-driven)

---

## Context Model

Inline requests should include context such as:

- tenant_id
- application_id
- logical_scope (optional)
- content_type (if known)
- user context (optional)
- workflow context (optional)

This enables:

- policy selection
- audit traceability
- differentiated behavior across applications

---

## Policy Integration

Policy evaluation is:

- centralized in DSX-Connect
- independent of the calling application
- consistent across inline and async flows

Policy may consider:

- protected scope (if repository-backed)
- logical application scope (inline)
- content type
- verdict classification
- tenant-specific rules

---

## Identity Considerations

Inline objects may not yet exist in a repository.

Therefore:

- DSX-Connect may assign a temporary or synthetic identity
- Identity may later be reconciled with a repository object
- Idempotency may rely on:
    - hash
    - upload session ID
    - client-provided correlation ID

---

## Performance Considerations

Inline scanning must balance:

- latency
- throughput
- file size constraints

Strategies may include:

- streaming scan
- size-based routing (inline vs async fallback)
- timeout thresholds
- async deferral for large files

---

## Error Handling

Errors should be explicit and structured:

- scan_failed
- fetch_failed
- timeout
- unsupported_file
- policy_error

Applications should be able to:

- fail closed (block on uncertainty)
- fail open (allow with audit)
- defer (retry or async fallback)

---

## Relationship to Connectors

Inline scanning:

- does NOT require connectors
- may optionally use connectors for:
    - reference fetch
    - remediation after decision

Connectors remain important for:

- repository scanning
- event-driven ingestion

But are not required for inline use cases.

---

## Relationship to Job Model

Inline requests may:

- bypass queue entirely (true synchronous)
- optionally emit audit/job records
- optionally trigger async follow-up workflows

This model must coexist with:

- batch/async scanning
- repository-driven jobs

---

## Example

### Application Upload Flow

1. User uploads resume to application
2. Application sends file to DSX-Connect
3. DSX-Connect returns:
    - verdict: malicious
    - decision: block
    - reason: malware_detected
4. Application rejects upload

---

### Large File Flow

1. Application sends reference (e.g., pre-signed URL)
2. DSX-Connect fetches and scans
3. Returns decision
4. Application proceeds accordingly

---

## Open Questions

- What are the hard limits for synchronous scanning (size/time)?
- Should DSX-Connect support async fallback automatically?
- How do we expose streaming vs buffered APIs?
- Should inline and async share a unified API surface?
- How do we represent partial results or progressive scanning?

---

## Current Direction

DSX-Connect should provide:

- a clean, stable inline API
- consistent decision semantics
- shared policy and audit across all flows

This is the foundation of:

> DSX-Connect as a Security Hub and File Scanning as a Service