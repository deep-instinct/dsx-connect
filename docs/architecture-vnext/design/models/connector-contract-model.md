# Connector Contract Model

## Purpose

This document defines the expected role and contract of integrations/connectors in the new DSX-Connect architecture.

The goal is to keep connectors simple and move orchestration, policy, and job ownership into core.

---

## Design Principle

A connector should act as a **platform adapter and data provider**, not as the owner of:

- policy
- counting
- orchestration
- final decisioning

---

## Connector Responsibilities

A connector is responsible for:

- authenticating to the target platform
- enumerating objects within configured scope(s)
- returning object batches and continuation cursors
- providing stable object identity and minimal metadata
- exposing repository read semantics either:
  - through a connector-owned read capability consumed by a `ConnectorProxyReader`
  - or by supplying normalized read hints that a native Reader can use
- performing remediation actions where supported and authorized
- surfacing platform-specific errors and capabilities

---

## Connector Must Not Own

A connector must not be the authoritative owner of:

- accepted job counts
- terminal job state
- policy enforcement logic
- workflow routing
- manual review state
- decision normalization

---

## Enumeration Contract

The connector should support batch-based enumeration.

### Input

Core provides:
- integration context
- target protected scope
- cursor, if continuing
- optional enumeration options

### Output

Connector returns:
- batch of items
- next cursor, if more items remain
- optional discovery metadata

---

## Item Shape

Each enumerated item should include, at minimum:

- `object_id`
- `object_locator`
- `scope_hint` or enough information for core to resolve scope
- `name`
- `content_type` if known
- `size` if known
- `etag` / version / last_modified where available
- minimal platform metadata

The item should be lightweight and should not require immediate full-content transfer during enumeration.

---

## Read Contract

A connector may participate in content acquisition in one of two ways.

### Proxy Read Capability
The connector exposes a stable read contract that a worker-side `ConnectorProxyReader` can call.

Expected request context includes:

- integration identifier
- scope identifier where relevant
- object identity
- normalized content source
- normalized read hints
- preferred response modes such as `stream`, `artifact_ref`, or `buffer`

Expected response semantics include:

- stream body
- buffered bytes
- or a temporary artifact reference

### Native Reader Support
The connector does not serve bytes directly, but provides normalized identity and read hints that a DI-owned native Reader can use.

This is the optimized path for integrations where DI chooses tighter first-order support.

---

## Remediation Contract

Where supported, the connector may expose remediation operations such as:

- move
- delete
- tag/label
- quarantine path move
- metadata mark

Core decides **whether** remediation should occur.
Connector performs **how** it occurs on that platform.

For the detailed remediation request/response contract, authority split, and 1g-to-2g migration model, see:

- [Remediation Contract Model](remediation-contract-model.md)

---

## Capability Advertisement

Each connector should declare platform capabilities, such as:

- supports monitoring
- supports enumeration
- supports versioned objects
- supports object tags/labels
- supports move
- supports delete
- supports server-side copy
- supports inline fetch streaming

This allows core to adapt behavior without hardcoding per-platform assumptions.

---

## Error Model

Connector errors should be categorized, not just logged as raw exceptions.

Suggested categories:
- auth_error
- permission_error
- transient_platform_error
- object_not_found
- rate_limit
- invalid_scope
- unsupported_operation

Core should determine retry behavior from category, not from string matching.

---

## Current Direction

The connector contract should be intentionally narrow:

- connector discovers
- connector may proxy reads
- connector remediates
- core decides
- core counts
- core owns workflow state

For version-aware enumeration and mutable-repository consistency expectations, see:

- [Asset Discovery Model](asset-discovery-model.md)
- [Version and Change Watermark Model](version-and-change-watermark-model.md)
- [Remediation Contract Model](remediation-contract-model.md)
- [Connector Deployment and Control Plane Ownership Model](connector-deployment-model.md)
