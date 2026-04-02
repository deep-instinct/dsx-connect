# API Surface Model (DSX-Connect Security Hub)

## Purpose

This document defines the external API surface for DSX-Connect as a **File Scanning as a Service (FSaaS)** platform.

The goal is to provide:

- a clean, stable interface for applications
- consistent decision semantics
- support for both synchronous and asynchronous scanning

---

## Design Principles

- **Simple first**: one primary API for most use cases
- **Consistent semantics**: same decision model across all endpoints
- **Separation of concerns**:
    - sync = decision now
    - async = process at scale
- **Transport-agnostic** where possible (stream, reference, connector)

---

## API Families

### 1. Inline (Synchronous) APIs — Primary

Used for:

- uploads
- real-time validation
- blocking decisions

---

### 2. Async / Job APIs — Secondary

Used for:

- large files
- bulk operations
- repository-driven scanning

---

### 3. Control Plane APIs — Supporting

Used for:

- scopes
- policy
- integrations
- audit

---

# 1. Inline Scan API

## Endpoint

POST `/v1/scan`

---

## Request Models

### Option A: File Upload (Multipart)

```json
Content-Type: multipart/form-data
file: <binary>
metadata: {
  "tenant_id": "t1",
  "application_id": "app1",
  "logical_scope": "uploads",
  "content_type": "application/pdf"
}
```

---

### Option B: Stream (Raw Body)

Headers:

```
Content-Type: application/octet-stream
X-Tenant-Id: t1
X-Application-Id: app1
X-Logical-Scope: uploads
```

Body:

```
<binary stream>
```

---

### Option C: Reference

```json
{
  "tenant_id": "t1",
  "application_id": "app1",
  "logical_scope": "uploads",
  "object_reference": {
    "type": "url",
    "value": "https://example.com/file.pdf"
  }
}
```

---

## Response Model

```json
{
  "request_id": "req-123",
  "verdict": "malicious | clean | suspicious | unknown",
  "decision": "allow | block | quarantine | hold_for_review",
  "reason": "malware_detected",
  "confidence": 0.98,
  "policy_id": "policy-abc",
  "processing_time_ms": 142,
  "metadata": {
    "file_type": "pdf",
    "size": 123456
  }
}
```

---

## Behavior

* Fully synchronous
* Returns final decision
* May internally:

    * stream scan
    * fetch content
    * evaluate policy

---

## Error Responses

```json
{
  "error": "scan_failed | timeout | fetch_failed | invalid_request",
  "message": "human readable message",
  "request_id": "req-123"
}
```

---

# 2. Async Scan API

## Endpoint

POST `/v1/scan/async`

---

## Request

Same as `/v1/scan`, but signals async execution.

---

## Response

```json
{
  "job_id": "job-456",
  "status": "accepted"
}
```

---

## Status Endpoint

GET `/v1/jobs/{job_id}`

```json
{
  "job_id": "job-456",
  "status": "pending | in_progress | completed | failed",
  "result": {
    "verdict": "clean",
    "decision": "allow"
  }
}
```

---

## Optional: Callback / Webhook

```json
{
  "callback_url": "https://app.example.com/webhook"
}
```

DSX-Connect POSTs result when complete.

---

# 3. Bulk / Batch API

## Endpoint

POST `/v1/scan/batch`

---

## Request

```json
{
  "tenant_id": "t1",
  "scope_id": "scope-123",
  "mode": "enumerate_and_scan"
}
```

---

## Behavior

* Triggers enumeration via connector
* Creates jobs internally
* Returns job group ID

---

## Response

```json
{
  "job_group_id": "group-789",
  "status": "started"
}
```

---

# 4. Control Plane APIs

## Integrations

* GET `/v1/integrations`
* POST `/v1/integrations`

---

## Protected Scopes

* GET `/v1/scopes`
* POST `/v1/scopes`

---

## Policy

* GET `/v1/policies`
* POST `/v1/policies`

---

## Audit / Events

* GET `/v1/audit`
* GET `/v1/events`

---

# 5. Decision Model (Canonical)

All APIs return decisions from the same set:

* allow
* block
* quarantine
* hold_for_review

This must remain consistent across:

* inline
* async
* batch

---

# 6. Idempotency

Optional header:

```
X-Idempotency-Key: <client-generated-id>
```

Used to prevent duplicate scans.

---

# 7. Size / Mode Routing (Future)

DSX-Connect may internally route:

* small files → inline
* large files → async

But API contract remains stable.

---

# 8. Authentication (Placeholder)

* API key
* OAuth / service identity
* mTLS (enterprise)

---

# 9. Open Questions

* Should `/scan` auto-fallback to async for large files?
* Do we unify sync/async into a single endpoint with mode hints?
* How do we support streaming responses for long scans?
* Should decision include remediation instructions or just outcome?

---

## Current Direction

Provide:

* one simple synchronous API for most use cases
* a parallel async model for scale
* consistent decision semantics across all flows

This API is the primary interface for:

> DSX-Connect as a Security Hub

```

