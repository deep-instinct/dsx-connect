# ADR-001: Reposition DSX-Connect as a Security Hub (File Scanning as a Service)

## Status

Proposed

## Context

DSX-Connect is currently positioned as a connector/orchestration layer that integrates DSXA into external platforms (S3, SharePoint, GCS, etc.), with some support for monitoring and async scanning.

This model introduces several limitations:

* Inline scanning is inconsistent and platform-specific
* Connectors become the center of the architecture
* Application developers must integrate differently per platform
* Decisioning, policy, and audit logic are fragmented across flows

At the same time, a growing set of use cases require:

* Inline upload protection
* Consistent file risk decisions across platforms
* A simple integration model for application developers
* Centralized policy and audit

This suggests a shift in perspective:

From:

> “How do we connect DSXA into platforms?”

To:

> “How do we provide file scanning as a service to any application or platform?”

---

## Decision

DSX-Connect will evolve toward a **Security Hub model**, acting as a:

* File Scanning Control Plane
* Decision Service for file risk
* Policy and audit layer

This establishes DSX-Connect as:

> A centralized service that evaluates file risk and returns decisions, independent of where the file originates.

---

## Key Capabilities

### Inline Security Services (Primary)

* Synchronous scan API:

    * “Scan this file now”
    * Returns verdict + action + reasoning

* Policy engine:

    * Tenant-aware
    * Application-aware
    * Content-aware

* Decision service:

    * allow
    * block
    * quarantine
    * hold (manual review)

* Audit + logging:

    * Full traceability of decisions

* Optional workflows:

    * Manual review / hold queues

---

### Platform / Repository Integrations (Secondary)

* Repository monitoring (S3, SharePoint, etc.)
* Event-driven ingestion
* Bulk / async scanning
* Enumeration via cursor/batch

These integrations feed into the same **policy + decision + audit layer**, but are no longer the primary architectural focus.

---

## Integration Model

### Application / Platform Pattern

1. Application receives file (upload, API, etc.)
2. Application calls DSX-Connect (inline API)
3. DSX-Connect evaluates file via DSXA + policy
4. DSX-Connect returns decision
5. Application enforces outcome (store, reject, quarantine)

**Important:**
DSX-Connect does not necessarily store files.
It acts as a **decision point before storage**.

---

### Developer Experience

Applications (CAP, Node, Java, etc.) integrate as clients:

* DSX-Connect becomes:

  > “File Scanning as a Service”

* No requirement to build connectors for inline use cases

---

## Consequences

### Positive

* Unified decision model across all platforms
* Clean integration for developers
* Centralized policy and audit
* Reduced duplication of scanning logic
* Stronger product positioning

### Tradeoffs / Risks

* Requires well-defined, stable API surface
* Shifts complexity into DSX-Connect core
* Connectors must be re-scoped and simplified
* May require rethinking current connector contracts

---

## Open Questions

* How should synchronous vs async APIs coexist?
* Where does file transfer responsibility live (streaming vs reference)?
* How are large files handled efficiently?
* What is the policy model (DSL, config, UI)?
* How do hold/manual-review workflows integrate with customers?

---

## Notes

* This ADR represents a **directional shift**, not a finalized implementation
* Connectors remain important, but become **secondary integration mechanisms**
* This aligns DSX-Connect more closely with a **control plane architecture**
