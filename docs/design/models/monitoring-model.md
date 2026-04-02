# Monitoring Model

## Purpose

This document defines how monitoring fits into the DSX-Connect architecture.

Monitoring is treated as a **capability of connector integrations**, not as a separate architectural layer.

---

## Core Principle

Monitoring belongs to **connector integrations**, because it involves observing systems that DSX-Connect does not directly control.

---

## What Is Monitoring?

Monitoring is the process of detecting:

- new objects
- modified objects
- deleted objects (optional)
- relevant platform events

and feeding those changes into DSX-Connect for evaluation.

---

## Why Monitoring Is Not a Top-Level Category

Monitoring is not its own integration pattern because:

- it always depends on a platform
- it requires platform-specific APIs or event systems
- it is tightly coupled to connectors

Therefore, monitoring is modeled as a **connector capability**, alongside:

- enumeration
- fetch
- remediation

---

## Monitoring Mechanisms

Different connectors may support different monitoring mechanisms:

### Event-Driven

- S3 event notifications
- GCS Pub/Sub
- SharePoint webhooks
- SaaS platform events

Pros:
- low latency
- efficient

Cons:
- requires platform support
- may require external configuration

---

### Polling

- periodic API queries
- filesystem scans

Pros:
- universal fallback
- simpler setup

Cons:
- higher cost
- increased latency
- potential duplication

---

### Hybrid

- event-driven primary
- polling as fallback or reconciliation

---

## Connector Responsibilities

For monitoring, connectors are responsible for:

- subscribing to or polling platform events
- translating platform events into normalized item representations
- submitting items to DSX-Connect core

Connectors should not:

- decide policy
- determine final outcomes
- track authoritative job state

---

## Core Responsibilities (DSX-Connect)

DSX-Connect core is responsible for:

- accepting monitored items
- deduplicating events where needed
- creating jobs
- evaluating policy
- triggering remediation
- maintaining audit trail

---

## Monitoring vs Enumeration

These are related but distinct:

### Monitoring
- reactive
- event-driven or polling-based
- focused on changes

### Enumeration
- proactive
- batch-based
- focused on full discovery

Both feed into the same job and decision pipeline.

---

## Example

### S3 Monitoring Flow

1. S3 emits object-created event
2. Connector receives event
3. Connector submits object to DSX-Connect
4. DSX-Connect scans and evaluates policy
5. If malicious → remediation triggered

---

## Design Goals

- near real-time detection where possible
- consistent handling across platforms
- minimal duplication
- reliable ingestion into job system

---

## Open Questions

- How do we handle duplicate or out-of-order events?
- What is the deduplication strategy?
- Should monitoring guarantee at-least-once or exactly-once semantics?
- How do we reconcile missed events?

---

## Current Direction

Monitoring should remain:

- a connector capability
- platform-specific in implementation
- normalized at the DSX-Connect core boundary