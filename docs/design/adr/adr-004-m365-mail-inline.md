# ADR-004: Microsoft 365 Mail Inline Integration

## Status

Proposed

---

## Context

Email remains one of the highest-risk entry points for malicious files.

Traditional approaches rely on:

* post-delivery scanning
* external gateways
* inconsistent enforcement

We need a model that aligns with DSX-Connect as a **Security Hub**.

---

## Decision

M365 mail will be integrated as a **Native Application Integration (inline pattern)** rather than a connector-first model.

---

## Model

### Inline Flow

1. Email received (with attachment)
2. Integration layer intercepts attachment
3. Calls DSX-Connect `/scan`
4. Receives decision
5. Enforces:

   * allow → deliver
   * block → remove
   * hold → quarantine

---

## Why Inline

* Decisions occur **before user access**
* Consistent with FSaaS model
* Reuses same API as applications
* Centralizes policy and audit

---

## Role of Connectors

Connectors still apply for:

* mailbox backlog scanning
* historical content
* monitoring changes
* remediation of existing items

---

## Consequences

### Positive

* real-time protection
* unified architecture
* consistent decisioning

### Tradeoffs

* requires platform-specific integration (Graph, add-ins, rules)
* latency considerations

---

## Open Questions

* best interception point (Graph vs transport rules)?
* attachment size limits?
* fallback to async for large attachments?

---

## Direction

Treat M365 as:

* **inline integration for new content**
* **connector integration for existing content**

This maintains a clean architectural model.
