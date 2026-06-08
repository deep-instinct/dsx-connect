# Version and Change Watermark Model

## Purpose

This document defines the connector-facing contract expectations for:

- object version metadata
- read-time version comparison
- change watermark / delta token support

This model supports the consistency semantics described in:

- [ADR-014: Full-Scan Consistency Model and Monitoring Convergence](../../adr/adr-014-full-scan-consistency-and-monitoring-convergence.md)

It is intended to guide connector implementers and core orchestration behavior.

---

## Core Principle

For mutable repositories, DSX-Connect should prefer **explicit version-aware truth** over implicit snapshot assumptions.

Connectors should provide enough metadata for core and Readers to answer:

- what object version was enumerated?
- what object version was read?
- what change boundary was active when baseline scan began?

---

## Why This Model Exists

A normal full scan operates on a live dataset.

That means:

- enumeration and read may observe different object versions
- new files may appear during the scan
- files may be deleted before read
- files may be modified after they were scanned

The architecture needs a connector contract that makes these cases visible rather than hiding them as generic scan failures or undocumented behavior.

---

## Connector Expectations

When the source platform allows it, connectors should surface:

- stable object identity
- enumerated version metadata
- change tracking tokens or watermarks
- read hints that preserve version-aware meaning

These should be treated as first-order contract fields, not incidental metadata.

---

## Object Version Metadata

## Enumerated Item Requirements

An enumerated object should include, where available:

- `object_identity`
- `size`
- `content_type`
- `etag`
- `version_id`
- `generation`
- `last_modified`
- provider-specific revision identifier

Not every platform supports every field.

The contract expectation is:

- provide what the platform can authoritatively supply
- do not synthesize fake version guarantees

## Normalized Shape

Suggested normalized structure:

```json
{
  "object_identity": "drive:abc/item:def",
  "size": 1048576,
  "content_type": "application/pdf",
  "version_info": {
    "etag": "\"12345\"",
    "version_id": null,
    "generation": null,
    "last_modified": "2026-05-26T14:30:00Z",
    "revision": null,
    "details": {}
  }
}
```

The `details` field may carry provider-specific values that do not fit the shared model cleanly.

---

## Read-Time Version Semantics

If the Reader or connector-proxy read path can observe read-time version metadata, that metadata should also be surfaced.

Core should be able to compare:

- enumerated version info
- read-time version info

This supports explicit classification of cases such as:

- `same_version`
- `version_changed_before_read`
- `deleted_before_read`

## Recommended Read Result Metadata

Suggested normalized structure:

```json
{
  "read_version_info": {
    "etag": "\"67890\"",
    "version_id": null,
    "generation": null,
    "last_modified": "2026-05-26T14:31:15Z",
    "revision": null,
    "details": {}
  }
}
```

If the platform does not expose read-time version information, the connector or Reader should omit it rather than inventing certainty.

---

## Change Watermarks and Delta Tokens

For connectors that support monitoring or change replay, the preferred contract is to expose a change boundary that can be used to reconcile baseline scan with later updates.

Examples:

- delta token
- change token
- event cursor
- sequence watermark
- provider-native revision checkpoint

## Watermark Semantics

The watermark should mean:

- “changes after this boundary can be fetched or replayed later”

This allows a baseline flow such as:

1. start full scan
2. capture watermark
3. enumerate and scan baseline content
4. process changes since watermark
5. continue monitored mode

This is the preferred convergence model for mutable repositories.

---

## Normalized Watermark Shape

Suggested structure:

```json
{
  "change_tracking": {
    "mode": "delta_token",
    "watermark": "abc123",
    "captured_at": "2026-05-26T14:30:00Z",
    "details": {}
  }
}
```

Possible `mode` values:

- `delta_token`
- `change_token`
- `event_cursor`
- `polling_watermark`
- `none`

---

## Connector Capability Advertisement

Connectors should advertise whether they support:

- enumerated version metadata
- read-time version metadata
- change watermarks
- change replay since watermark
- monitoring
- deletion events

Suggested capability examples:

- `supports_version_metadata`
- `supports_read_version_metadata`
- `supports_change_watermark`
- `supports_change_replay`
- `supports_monitoring`

This allows core to adapt behavior without hardcoding connector-specific assumptions.

---

## Core Behavior Expectations

When version metadata is available, core should:

- persist enumerated version info with the accepted item
- persist read-time version info when observed
- classify mismatches explicitly
- expose enough metadata for audit and replay planning

When change watermarks are available, core should:

- capture them when baseline scan begins
- persist them on the relevant scan or shard unit
- use them to reconcile post-baseline changes

When these features are not available, core should:

- fall back to live-dataset semantics
- avoid implying stronger guarantees than the connector can support

---

## Connector Rules

Connectors should:

- provide authoritative version metadata where available
- provide change watermarks where available
- preserve provider-native semantics in `details` when shared fields are insufficient
- avoid claiming snapshot or strict change guarantees unless the platform truly supports them

Connectors should not:

- invent synthetic version IDs to imply strong consistency
- silently drop known version metadata
- imply that opportunistically discovered new files are guaranteed inclusion in a full scan

---

## Recovery and Replay Implications

Version-aware identity becomes more important when replay is coarse-grained.

Examples:

- batch-level replay may re-read a later version of an item
- shard-level replay may include some objects in changed form relative to original enumeration

This is acceptable if:

- the architecture records that version drift occurred
- monitoring or replay semantics are clear
- operators are not misled into assuming snapshot precision

---

## Summary

The connector contract should support mutable-repository truthfulness by surfacing:

- stable object identity
- version metadata
- change watermarks

These are the enabling inputs for:

- live full-scan consistency modeling
- monitoring convergence
- version-aware replay and audit
