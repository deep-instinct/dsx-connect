# Quarantine Target Model

## Purpose

This note defines how `dsx_connect_ng` should represent quarantine destination and naming behavior in policy and remediation plans.

It exists to make quarantine behavior explicit across connectors instead of relying on ad hoc connector-local conventions.

---

## Core Principle

Quarantine policy should answer two separate questions:

1. where should the object go
2. what naming strategy should be applied to the quarantined artifact

These must be policy decisions, not hidden connector defaults.

---

## Recommended Target Shape

Suggested fields for a quarantine target:

- `path`
- `prefix`
- optional `repository`
- `preserve_relative_path`
- `collision_strategy`
- `suffix_length`

Example:

```json
{
  "path": "tenant-quarantine",
  "preserve_relative_path": false,
  "collision_strategy": "suffix_random",
  "suffix_length": 10
}
```

---

## Destination Strategies

Common destination patterns:

- same scope, quarantine subpath
- same repository, separate top-level quarantine area
- separate quarantine repository

Examples:

- `bucket-a/path/to/file.exe` -> `bucket-a/quarantine/path/to/file.exe`
- `share/site/docs/file.exe` -> `share/site/quarantine/docs/file.exe`
- `bucket-a/file.exe` -> `bucket-q/customer-a/file.exe`

The model should not assume that all platforms can support every strategy.

---

## Collision Strategies

Recommended normalized values:

- `suffix_random`
- `overwrite`
- `fail`

Default recommendation:

- `suffix_random`

Reason:

- every quarantined object is visibly quarantined
- prevents accidental overwrite without probing for collisions
- preserves the original filename for operator recognition
- allows repeated quarantines of similarly named objects
- disables the original terminal extension by appending the suffix at the very end

Recommended quarantine filename format:

- `<original_filename>_<suffix>`

Examples:

- original: `invoice.pdf`
- quarantined: `invoice.pdf_c23bbf85bc`
- original: `bad.exe`
- quarantined: `bad.exe_c23bbf85bc`

Recommended suffix source:

- first choice: normalized `job_item_id` token
  - strip `job_item_`
  - take the first `suffix_length` alphanumeric characters
- fallback: random lowercase alphanumeric token of `suffix_length`

---

## Connector Behavior

Connectors should treat quarantine naming as an execution concern, not a policy decision.

Core policy decides:

- target area
- suffixing strategy

Connector executes:

- move/copy/tag/delete using platform-native operations
- suffixing according to requested strategy when supported

If unsupported, connectors should return a normalized unsupported or degraded outcome instead of silently overwriting.

---

## Current 2g Direction

Current `dsx_connect_ng` policy config should default quarantine to:

- `preserve_relative_path = false`
- `collision_strategy = suffix_random`
- `suffix_length = 10`

This provides a safe deterministic default while leaving room for connector-specific implementation later.
