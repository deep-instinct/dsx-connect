# ADR-005: Asset Protection and Configuration Ownership

## Status

Proposed

---

## Context

DSX-Connect is responsible for protecting assets across external platforms (e.g., S3, SharePoint, GCS).

Historically, protection mechanisms have required:

* modifying platform configurations (e.g., S3 event notifications)
* deploying platform-native components (e.g., Lambda)
* potentially overwriting or interfering with existing customer configurations

Example issue:

* S3 event notifications are not additive in a safe way
* configuring DSX-Connect monitoring may overwrite existing notifications
* creates risk of breaking customer workflows

This raises a key architectural question:

> Should DSX-Connect modify platform configuration to enforce protection, or operate within existing platform constraints?

---

## Decision

DSX-Connect will adopt a **non-destructive integration model**:

> It must not overwrite or disrupt existing customer configurations on protected assets.

Instead, DSX-Connect will prefer:

* additive or cooperative configuration where supported
* external observation and ingestion where possible
* explicit ownership boundaries when modification is required

---

## Key Principles

### 1. Do Not Break Existing Behavior

* Never overwrite:

    * event notifications
    * policies
    * access controls

* Avoid:

    * destructive updates
    * exclusive ownership assumptions

---

### 2. Prefer Observational Integration

Where possible, DSX-Connect should:

* consume existing signals (events, logs, APIs)
* avoid requiring configuration changes
* operate as a **consumer**, not a controller

Examples:

* CloudTrail / audit logs
* existing event buses
* shared notification channels

---

### 3. Explicit Ownership When Required

If DSX-Connect must modify configuration:

* it must be clearly scoped
* explicitly owned
* reversible
* isolated from unrelated settings

Examples:

* dedicated event bridge rules
* separate notification pipelines
* isolated resources (queues, topics)

---

### 4. Separation of Concerns

Split responsibilities:

* **Platform configuration**

    * owned by customer or platform team

* **Security decisioning**

    * owned by DSX-Connect

DSX-Connect should not become a general-purpose configuration manager.

---

### 5. Integration Mode Awareness

Different integration types have different expectations:

#### Native / Inline Integrations

* do not modify platform config
* operate within application flow

#### Connector Integrations

* may require limited configuration
* must follow non-destructive principles

---

## Example: AWS S3

### Problem

* S3 event notifications are not safely mergeable
* DSX-Connect configuration may overwrite existing notifications

### Direction

Prefer:

* EventBridge-based ingestion
* shared or additive event routing
* separate DSX-managed pipeline

Avoid:

* directly replacing bucket notification configuration

---

## Example: Monitoring vs Control

DSX-Connect should:

* monitor and react to events
* not assume control over event generation

---

## Consequences

### Positive

* safer customer deployments
* avoids breaking existing integrations
* easier adoption in complex environments
* aligns with principle of least disruption

---

### Tradeoffs

* may require more complex ingestion logic
* less control over event fidelity
* reliance on platform capabilities
* may require fallback strategies (polling, reconciliation)

---

## Open Questions

* How do we handle platforms with no non-destructive integration options?
* Should DSX-Connect offer a “managed mode” with stronger control?
* How do we validate that monitoring coverage is complete?
* What is the fallback when events are missed?

---

## Relationship to Other ADRs

* ADR-002 (Tenant Connectors)
  → defines scope ownership within integrations

* ADR-003 (Enumeration & Jobs)
  → provides fallback when monitoring is incomplete

* ADR-001 (Security Hub)
  → reinforces separation between control plane and platform configuration

---

## Current Direction

DSX-Connect should act as:

> a security control plane that **observes and protects**, not one that **reconfigures and owns** external systems.

This ensures compatibility with real-world enterprise environments where:

* multiple systems coexist
* configurations are shared
* disruption is unacceptable
