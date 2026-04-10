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
- retrieving object content or a content stream when needed
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

## Fetch Contract

A connector should support one or both of these patterns:

### Reference Fetch
Core receives a fetchable locator and requests content later.

### Streamed Fetch
Connector streams content directly for synchronous or worker-driven scanning.

The preferred pattern may vary by platform and file size.

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
- connector fetches
- connector remediates
- core decides
- core counts
- core owns workflow state