# Remediation Contract Model

## Purpose

This document defines the runtime contract for repository mutation in `dsx_connect_ng`.

It covers:

- who decides remediation behavior
- what the core-to-connector remediation request should contain
- what the connector must return
- how 1g connector compatibility should work during migration

---

## Core Principle

Policy and remediation intent belong to core.

Connectors execute repository-native mutation.

The authority split is:

- core decides whether to remediate
- core decides which action is requested
- connector executes the requested action if supported
- connector reports the execution outcome

Connectors must not be the policy authority.

---

## Why This Changes from 1g

In 1g, many connectors effectively decided remediation behavior from connector-local settings such as:

- `item_action`
- `item_action_move_metainfo`

That created an authority inversion:

- core detected a malicious or otherwise relevant outcome
- connector-local config decided whether to move, delete, or tag

This caused inconsistent behavior, weaker auditability, and harder policy management across scopes and platforms.

In 2g, remediation policy is part of the control plane and workflow state. Connectors should act as execution engines, not policy engines.

---

## Remediation Scope

The remediation contract applies to repository mutation actions such as:

- `nothing`
- `delete`
- `move`
- `tag`
- `movetag`

These are connector-facing execution actions.

Core policy may express higher-level intent such as:

- `detect_only`
- `quarantine`
- `delete`
- `tag_only`

Core is responsible for translating those policy outcomes into connector-facing execution actions.

For quarantine-style remediation, that translation must also carry:

- quarantine destination strategy
- relative-path preservation behavior
- collision behavior for repeated quarantines of similarly named objects

---

## Request Contract

The core-to-connector remediation request should be authoritative and request-driven.

At minimum it should contain:

- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `content_source`
- `requested_action`
- optional execution metadata such as `scan_guid`, verdict, or audit tags

### Example Request

```json
{
  "job_id": "job_123",
  "job_item_id": "job_item_456",
  "integration_id": "gcs-tenant-a",
  "scope_id": "bucket-b1",
  "object_identity": "b1/path/to/file.exe",
  "content_source": {
    "mode": "original",
    "locator": "b1/path/to/file.exe"
  },
  "requested_action": {
    "type": "movetag",
    "destination": {
      "path": "quarantine/"
    },
    "tags": {
      "dsx_verdict": "malicious"
    }
  },
  "scan_context": {
    "scan_guid": "scan_001",
    "verdict": "Malicious"
  }
}
```

### Requested Action Rules

`requested_action` should be explicit.

The connector must not infer the intended action from connector-local remediation policy.

For example:

- `delete` means delete the object
- `move` means move to the requested destination
- `tag` means apply the requested tags without moving the object
- `movetag` means move and apply tags if supported
- `nothing` means no repository mutation is required

If a requested action is unsupported, the connector should return a normalized unsupported result rather than silently substituting another action.

### Quarantine Destination and Naming

Quarantine should be policy-driven, not connector-local guesswork.

At minimum, quarantine planning should support:

- `path` or `prefix` for the destination area
- optional repository selector when the quarantine area is not the original repository
- whether to preserve the original relative path
- naming/suffix strategy for the quarantined artifact

Recommended collision strategies:

- `suffix_random`
- `overwrite`
- `fail`

Default recommendation:

- preserve the original filename
- always append a unique suffix at the very end of the quarantined filename
- derive the suffix from normalized `job_item_id` when available
- fall back to a random lowercase alphanumeric suffix when workflow identity is unavailable

Example:

- original: `invoice.pdf`
- quarantined: `invoice.pdf_c23bbf85bc`

This avoids accidental overwrite, keeps repeated quarantines distinct, and neutralizes the original terminal extension.

---

## Response Contract

The remediation response should tell core what actually happened.

At minimum it should contain:

- `status`
- `applied_action`
- optional `target_path`
- optional connector-native details
- optional structured error information

### Example Response

```json
{
  "status": "success",
  "applied_action": "movetag",
  "target_path": "quarantine/path/to/file.exe",
  "details": {
    "tag_applied": true
  }
}
```

### Normalized Status Values

Suggested normalized statuses:

- `success`
- `nothing`
- `not_supported`
- `permission_error`
- `object_not_found`
- `transient_platform_error`
- `error`

Core should reason over normalized outcomes instead of connector-specific strings where possible.

---

## Capability Model

Connectors should explicitly advertise remediation capabilities, including:

- supports delete
- supports move
- supports tag/label
- supports move and tag in one logical operation
- supports overwrite semantics where relevant
- supports metadata-preserving move where relevant

Connectors may differ in how much quarantine destination flexibility they support:

- same repository, alternate prefix/path
- same repository, same-scope quarantine subpath
- separate quarantine repository
- collision avoidance via rename/suffix vs native overwrite flags

This allows policy and remediation planning to fail early or degrade cleanly when a requested action is impossible on a given platform.

---

## Relationship to Readers

Readers are not the remediation boundary.

Readers exist to acquire content for scan-time or post-scan processing.

Repository mutation remains connector-owned because delete, move, and tag behavior are platform-native operations.

The intended split is:

- connector owns enumeration
- Reader owns content acquisition
- connector owns repository mutation
- core owns orchestration and policy

---

## Migration Model

### 1g Connector Compatibility

`dsx_connect_ng` must continue to interoperate with existing 1g connectors during transition.

That compatibility layer may:

- translate 2g requested actions into legacy `item_action` request shapes
- supply legacy move metadata fields where expected
- tolerate connectors that are still partially config-driven

This compatibility mode is transitional and may be best-effort on some platforms.

### Native 2g Connectors

The long-term target is a clean 2g connector contract where:

- remediation is per-request and authoritative
- connector-local remediation policy is removed
- connector responses are normalized and testable
- capability advertisement is explicit

Separating native 2g connectors from legacy 1g connectors is the cleanest long-term architecture.

---

## Operational Expectations

The remediation contract should support at-least-once execution semantics.

That means:

- core should be prepared to retry
- connectors should behave safely on duplicate requests where possible
- responses should be structured enough for idempotent handling and auditing

For producer-side reliability and consumer-side duplicate tolerance, see:

- [ADR-013: Tunable Recovery Granularity and Transaction Outbox](../../adr/adr-013-tunable-recovery-granularity-and-transaction-outbox.md)

---

## Current Direction

`dsx_connect_ng` should treat remediation as a first-class stage with:

- policy-driven action selection in core
- connector-driven mutation execution
- explicit request and response contracts
- compatibility bridging for 1g connectors
- a clear path to native 2g connectors
