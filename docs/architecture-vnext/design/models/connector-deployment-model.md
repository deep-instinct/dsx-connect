# Connector Deployment and Control Plane Ownership Model

## Purpose

This document explains how connector deployment should work in the 2g architecture.

It exists to make one architectural shift explicit:

- 1g treated connectors as more free-standing runtime entities
- 2g treats connectors as repository adapters managed by the control plane

This does not mean every connector must be physically embedded in the core process.
It means the control plane is authoritative for connector intent, configuration, and binding ownership.

---

## Core Principle

In 2g, a connector should be understood as a **managed platform adapter**.

The control plane owns:

- integration definition
- scope attachment
- policy attachment
- secret references
- reader mode
- monitoring configuration
- remediation capability model
- connector endpoint/runtime configuration

The connector runtime executes repository-specific behavior on behalf of that integration.

---

## Shift From 1g

In 1g, connectors often carried a mixed bundle of concerns:

- repository credentials and account info
- monitoring/pub-sub wiring
- deployment/runtime settings
- policy behavior
- remediation behavior
- runtime registration into core

2g removes policy ownership from connectors and centralizes orchestration in core.

Once Readers and request-driven remediation are part of the model, core necessarily needs to understand:

- how to reach the connector
- what credentials or secret references exist
- what repository scope is being protected
- what monitoring mode is enabled

So the 2g boundary is not:

- "core knows nothing about connector deployment"

The 2g boundary is:

- "core owns integration intent and lifecycle"
- "connector owns repository-native execution"

More precisely for runtime operations:

- DSX-Connect owns integration intent, endpoint binding, and health assessment
- Kubernetes or equivalent orchestration owns runtime lifecycle, scaling, placement, restart, and rollout behavior

---

## Ideal Deployment Shape

The preferred operational model is:

- connectors are deployed within the same container environment as `dsx_connect_ng`

This is ideal because it simplifies:

- networking
- secret projection
- health visibility
- operator binding
- version alignment between core and connector runtime

Examples:

- same Kubernetes namespace
- same Helm release
- same Compose project
- same control-plane-managed runtime environment

This does **not** require that connectors run in the same process.

The important point is shared deployment environment, not process co-location.

---

## Non-Ideal but Supported Shape

Connectors may still run as separate services or deployments when needed.

Examples:

- separate deployment for platform-specific dependencies
- separate scaling boundary
- tenant-isolated runtime
- externally managed runtime in constrained environments

In that case, the integration record still remains the source of truth for:

- connector endpoint
- secret references
- capabilities
- monitoring behavior
- remediation behavior

So the difference is deployment topology, not ownership model.

In both cases, DSX-Connect should avoid becoming a runtime orchestrator.

---

## 2g Discovery Model

In 2g, connectors should not be "discovered" primarily through 1g-style runtime self-registration.

Instead:

1. an operator or automation creates an integration in the control plane
2. the integration config defines connector/runtime details
3. jobs reference the integration
4. workers call the configured connector endpoint directly

So in 2g, "registration" is really:

- provisioning or updating the integration record

not:

- connector posting itself into core as the source of truth

This is why 1g runtime self-registration can be disabled for 2g-targeted local runs.

---

## Secret and Account Ownership

Because 2g Readers and remediation are orchestrated by core, there is no real path where core can remain unaware of:

- repository account information
- credential references
- tenant/project identifiers
- monitoring configuration

That is acceptable and expected.

The architectural requirement is not "core must not know credentials exist."

The requirement is:

- core owns credential metadata and secret references
- secret material should live in a proper secret backend
- runtimes should receive only the credentials they need

Examples:

- Kubernetes Secret references
- external secret managers
- mounted runtime credentials
- per-integration secret handles

---

## Orchestration Boundary

DSX-Connect should not attempt to replace Kubernetes or another deployment platform.

Connector runtime concerns such as:

- scaling replicas
- restart policy
- rollout orchestration
- placement across nodes or clusters
- service discovery wiring
- autoscaling

should remain the responsibility of Kubernetes or the surrounding deployment platform.

DSX-Connect should instead own:

- integration creation
- connector endpoint binding
- secret-reference association
- capability declaration
- scope attachment
- health and readiness assessment

This keeps DSX-Connect in the control-plane lane rather than turning it into a second scheduler.

## Runtime Modes

The control plane should support at least two deployment modes.

### Mode A: Same-Environment, Platform-Managed Connector Runtime

The connector runtime is deployed in the same container environment as DSX-Connect, but lifecycle is still managed by Kubernetes or the surrounding platform.

Examples:

- same Helm release
- same namespace
- same Compose project
- shared secrets and networking policy

This is the preferred operational shape.

### Mode B: Externally Managed Connector Runtime

The connector runtime exists outside direct core deployment ownership, but the control plane still owns the integration record.

Examples:

- operator provides a connector endpoint
- separate deployment pipeline manages the connector
- specialized runtime is hosted independently

This is useful for flexibility, but it should not change the control-plane model.

---

## Health Model

Connector health in 2g should be treated as:

- a control-plane health and observability concern

not:

- a discovery mechanism

The control plane may assess health through:

- explicit connector health endpoints
- repository connectivity checks
- recent successful read/remediation activity
- optional heartbeats

But health should not be required to define integration existence.

Integration existence comes from configuration.
Health describes runtime viability.

---

## UI-Driven Provisioning

One strong benefit of the 2g model is that the UI can become the natural place to configure and bind connectors.

Typical flow:

1. user chooses a platform type
2. user enters account/tenant/project details
3. user attaches or references credentials
4. user defines scope(s)
5. user selects monitoring/full-scan options
6. control plane creates integration record
7. operator binds the integration to a connector endpoint already deployed by Kubernetes or another platform
8. health and readiness are surfaced back through the UI
9. DSX-Connect begins using the runtime for read/monitor/remediation operations

This is much cleaner than a model where connectors are provisioned separately and then partially taught platform behavior or policy.

---

## Recommended Direction

The recommended 2g deployment model is:

- control plane owns integrations
- policy stays out of connectors
- connectors are repository adapters
- same deployment environment as core is preferred
- separate deployment topology remains supported
- Kubernetes or equivalent orchestration owns runtime lifecycle
- runtime self-registration is optional legacy behavior, not the primary 2g discovery path

This keeps the architecture operationally realistic while supporting the long-requested UX of control-plane-driven connector binding and validation.

---

## Related Models

- [Connector Contract Model](connector-contract-model.md)
- [Reader Contract Model](reader-contract-model.md)
- [Monitoring Model](monitoring-model.md)
- [Remediation Contract Model](remediation-contract-model.md)
