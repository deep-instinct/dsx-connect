# ICAP Integration Model

## Purpose

This document defines how DSX-Connect can participate in ICAP-based inline enforcement flows while preserving its broader role as a Security Hub for asynchronous orchestration and enrichment.

This model is especially relevant for:

- NAS and file share integrations
- secure web gateway style flows
- mail and attachment inspection flows
- enterprise environments that already use ICAP as an inline enforcement surface

---

## Core Principle

DSX-Connect can act as an **ICAP-facing inline decision service**.

In this model:

- DSX-Connect receives the ICAP transaction
- invokes DSXA for fast malware decisioning
- returns an immediate inline disposition
- asynchronously triggers deeper post-processing workflows

This creates a split-phase architecture:

- **Phase 1: fast inline enforcement**
- **Phase 2: asynchronous enrichment and orchestration**

---

## Why ICAP Fits the Architecture

ICAP is a transport and enforcement surface, not the full architecture.

DSX-Connect remains the control plane responsible for:

- decision orchestration
- policy evaluation
- audit and logging
- workflow execution
- post-processing and enrichment

ICAP simply provides a low-latency mechanism for asking:

> “Can this file proceed right now?”

---

## High-Level Flow

1. Client or platform sends file through ICAP flow
2. DSX-Connect receives the ICAP request
3. DSX-Connect invokes DSXA for fast-path scan decision
4. DSX-Connect applies fast-path policy
5. DSX-Connect returns ICAP disposition
6. DSX-Connect schedules asynchronous post-processing
7. Workers enrich and evaluate deeper controls

---

## Two-Phase Evaluation Model

### Phase 1: Inline Enforcement Path

Optimized for:

- low latency
- deterministic response
- access-path enforcement

Responsibilities:

- receive ICAP request
- normalize request metadata
- invoke DSXA
- evaluate fast-path policy
- return allow/block style disposition quickly

This path should remain intentionally narrow.

---

### Phase 2: Post-Processing Path

Optimized for:

- richer analysis
- non-blocking workflows
- broader security and compliance outcomes

Responsibilities:

- persist event and metadata
- store durable reference or object identity where possible
- trigger worker jobs
- enrich with DIANNA
- run DLP and classification
- update audit trail
- trigger notifications, workflows, or later remediation

---

## Signal Model

### Fast-Path Signals

Signals allowed in the critical inline path should be those that can meet strict latency requirements.

Examples:

- DSXA malware verdict
- minimal request context
- limited fast-path policy checks

---

### Extended Signals

Signals used after the inline response may include:

- DIANNA enrichment
- DLP results
- content classification
- tenant-specific compliance logic
- additional external enrichment systems

---

## Policy Model

The ICAP pattern suggests two practical policy layers.

### Fast-Path Policy

Used in the inline critical path.

Typical examples:

- block if DSXA verdict is malicious
- allow if DSXA verdict is clean
- fail closed on scan error in high-security mode
- fail open with audit in lower-friction mode

This policy must remain simple and latency-safe.

---

### Extended Policy

Used in asynchronous processing.

Typical examples:

- alert if DIANNA indicates elevated threat reputation
- trigger compliance workflow on DLP match
- add metadata or labels based on classification
- initiate later remediation if policy requires it

This policy can be richer because it is not in the blocking request path.

---

## Result Semantics

It is important to distinguish between what is decided inline and what may be learned later.

### Inline Disposition

The immediate decision returned to the ICAP caller.

Examples:

- allow
- block

Depending on the ICAP usage model, this may map to vendor-specific response semantics.

---

### Post-Processing Findings

Findings discovered after the inline response.

Examples:

- DLP match
- suspicious intelligence correlation
- sensitive content classification
- policy violation requiring later action

These findings do not retroactively change what was returned inline, but they may trigger follow-on actions.

---

### Follow-On Actions

Examples:

- alert SOC
- notify administrator
- quarantine later
- tag or classify content
- open case or manual review

---

## Deployment Patterns

### Pattern 1: DSX-Connect as ICAP-Facing Service

DSX-Connect directly implements the ICAP service surface.

Use when:

- DSX-Connect is expected to sit directly in the enforcement path
- minimal extra components are desired

---

### Pattern 2: ICAP Adapter in Front of DSX-Connect

A lightweight adapter handles ICAP protocol details and forwards normalized requests to DSX-Connect.

Use when:

- protocol isolation is preferred
- specialized deployment requirements exist
- teams want to keep DSX-Connect’s core API transport-agnostic

---

## Relationship to NAS and Similar Integrations

In NAS scenarios such as NetApp VScan- or Dell EMC-style patterns, ICAP can provide the inline decision path.

That means DSX-Connect can support:

- immediate malware-based enforcement through DSXA
- asynchronous enrichment through workers
- later policy-driven actions beyond the initial allow/block result

This aligns enterprise file access flows with the same Security Hub architecture used for apps and repositories.

---

## Architectural Benefits

### Low-Latency Enforcement

Supports fast inline decisions where blocking latency matters.

### Broader Security Value

Preserves asynchronous enrichment and orchestration beyond the initial malware decision.

### Unified Control Plane

Uses the same policy, audit, and workflow model as the rest of DSX-Connect.

### Extensibility

Allows future enrichment services without complicating the inline path.

---

## Constraints and Considerations

### Latency

The inline ICAP path must remain fast and predictable.

### File Size

Large files may require special handling, streaming, or operational limits.

### Fail Behavior

Clear fail-open vs fail-closed behavior must be configurable.

### Reference Durability

Post-processing requires enough identity, metadata, or retained content to analyze later.

### Result Transparency

Operators must understand the difference between inline disposition and later findings.

---

## Open Questions

- Should DSX-Connect implement ICAP directly or use an adapter?
- What are acceptable latency budgets for inline ICAP flows?
- What content or metadata must be retained for asynchronous enrichment?
- How should fail-open vs fail-closed be expressed in policy?
- Which signals are allowed in fast-path policy by default?

---

## Current Direction

DSX-Connect should treat ICAP as a **low-latency inline enforcement surface** that integrates cleanly with its broader role as:

- a Security Hub
- a multi-signal decision engine
- an asynchronous orchestration platform

This allows DSX-Connect to combine:

- **fast inline enforcement**
- **deeper asynchronous enrichment**
- **unified policy and audit**