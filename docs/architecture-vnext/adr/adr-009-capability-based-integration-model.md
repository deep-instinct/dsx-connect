# ADR-008: Capability-Based Integration Model (Connector vs Worker Responsibilities)

- **Status:** Proposed
- **Date:** 2026-04-10
- **Supersedes:** None
- **Related:** ADR-007 (Reader-Based Read Path and Registration Model)

---

## Context

ADR-007 introduced the concept of **Reader-based data-plane execution**, moving repository read operations from connectors into worker-hosted components.

During that design, a broader pattern emerged:

Instead of thinking in terms of:
- connectors expose functions (read, enumerate, remediate)

We can think in terms of:
- integrations provide **capabilities**, and
- different parts of the system execute those capabilities

Example:

```yaml
aws.s3:
  - read
  - enumerate
  - remediate
````

This raises an important architectural question:

> Where should these capabilities actually execute?

Historically:

* connectors owned most integration logic (read, enumerate, remediate)
* workers were mostly execution engines for scanning only

In the new architecture:

* connectors are expanding to represent **entire tenants/accounts**
* protected scopes are owned by core
* workers are already the **horizontally scalable execution layer**

This creates pressure to move **heavy, repeatable, high-throughput operations** (like read and enumeration) into the worker tier.

---

## Decision

DSX-Connect will adopt a **capability-based integration model** with clear separation of responsibilities:

### Connector = Integration Authority (Control Plane)

Responsible for:

* integration registration
* configuration validation
* authentication setup and validation
* discovery of protectable assets
* mapping platform constructs → DSX-Connect object model
* monitoring setup (webhooks, polling, subscriptions)
* credential brokerage and access delegation (see future ADR)
* defining integration contract (object identity, context schema)

The connector is **not** responsible for executing high-volume per-object operations in the steady-state architecture.

---

### Worker = Capability Executor (Data Plane)

Responsible for executing capabilities that require:

* high concurrency
* horizontal scalability
* per-object or per-batch execution

This includes:

* `read` (via Readers, ADR-007)
* `enumerate` (full scan traversal, listing objects)
* potentially parts of `remediate` (object-level actions, where appropriate)

Workers execute these capabilities using integration-provided implementations (e.g., Readers or similar plugins), resolved via the registry.

---

### Core = Policy and State Authority

Responsible for:

* protected scope definitions
* job creation and orchestration
* job state and lifecycle
* authoritative counters (accepted, processed, terminal)
* policy decisions (scan, block, allow, remediate)
* coordination between connector and worker layers

Core does **not** perform integration-specific operations.

---

## Key Architectural Shift

The system moves from:

> connectors expose behavior and execute it

to:

> integrations define capabilities, and workers execute them

---

## Capability Placement Principles

To determine where a capability belongs:

### Belongs in Connector (Control Plane) if:

* it is low-frequency or setup-oriented
* it defines or validates integration configuration
* it establishes or manages monitoring/event subscriptions
* it defines object identity or mapping rules
* it requires authoritative integration context
* it involves credential issuance or delegation

Examples:

* discovery of available repositories/sites/buckets
* webhook or event subscription setup
* initial scope validation
* credential brokering

---

### Belongs in Worker (Data Plane) if:

* it is high-frequency or per-object
* it benefits from horizontal scaling
* it is part of scan execution or bulk processing
* it operates on already-normalized object identity

Examples:

* reading file content (`read`)
* enumerating large object sets for full scan (`enumerate`)
* executing per-object remediation actions (delete, move, tag), where safe

---

## Enumeration as a Capability

Enumeration (listing objects for full scans) is explicitly recognized as a **data-plane capability**.

In the new model:

* connectors define **what can be enumerated**
* core defines **what should be enumerated (scope)**
* workers execute **how enumeration happens at scale**

This avoids:

* connector bottlenecks during large full scans
* need for connector sharding to handle enumeration load
* duplication of enumeration logic across connectors

---

## Remediation as a Capability

Remediation may be split:

* **control-plane aspects** (what actions are allowed, policy, validation) remain connector/core responsibilities
* **execution aspects** (performing object-level actions) may be executed in workers where safe and scalable

This should be treated carefully per integration due to permission and safety concerns.

---

## Integration Capability Declaration

Integrations should declare supported capabilities:

```yaml
aws.s3:
  capabilities:
    - read
    - enumerate
    - remediate
```

This allows:

* dynamic capability checks
* future extensibility
* clearer system behavior when capabilities are partially supported

---

## Relationship to ADR-007

ADR-007 defined:

* Reader abstraction
* registry-based resolution
* worker-hosted read path

ADR-008 generalizes that idea:

* Reader is one instance of a broader **capability execution model**
* other capabilities (enumerate, remediate) may follow similar patterns

---

## Benefits

### Removes Connector Bottlenecks

High-volume operations no longer funnel through connectors.

### Aligns Workload with Scalable Tier

Workers already provide concurrency, retry, and throughput controls.

### Simplifies Connector Responsibilities

Connectors become cleaner, focusing on integration authority rather than execution.

### Enables Capability-Based Extensibility

Integrations declare what they support instead of exposing arbitrary APIs.

### Supports Future Growth

New capabilities can be introduced without redefining core architecture.

---

## Tradeoffs

### Increased System Complexity

Capability distribution requires clear contracts and coordination.

### Credential Handling Becomes Critical

Workers executing capabilities must obtain secure, scoped access to repositories.

### Stronger Contracts Required

Object identity, enumeration context, and action semantics must be well-defined.

### Potential Duplication Risk

Without discipline, capability implementations could drift between integrations.

---

## Risks

### Credential Exposure

Moving execution to workers increases the surface area where credentials or tokens may be used.

### Capability Drift

Different integrations may implement capabilities inconsistently if contracts are not strict.

### Overloading Workers

Workers may take on too many responsibilities if capability boundaries are not enforced.

---

## Consequences

* connectors will no longer be the primary execution point for read and enumeration
* workers will execute more integration-aware operations via registered capabilities
* integration packages must include both control-plane and data-plane components
* capability registration becomes a first-class concept in DSX-Connect

---

## Follow-On Work

1. define capability interfaces (read, enumerate, remediate)
2. extend registry model to support multiple capability types
3. define enumeration contract and batching model
4. define remediation execution boundaries
5. design credential brokerage and delivery model (critical)
6. define packaging/deployment model for capability implementations

---

## Summary

DSX-Connect will adopt a capability-based integration model in which:

* connectors act as integration authorities (control plane)
* workers execute integration capabilities (data plane)
* core owns policy and state
* integrations declare capabilities instead of exposing behavior directly

This enables the system to scale high-volume operations like read and enumeration in the worker tier, while keeping connectors focused, consistent, and aligned with the new tenant/account-wide architecture.

```
```
