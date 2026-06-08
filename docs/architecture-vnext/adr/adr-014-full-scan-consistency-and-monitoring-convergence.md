# ADR-014: Full-Scan Consistency Model and Monitoring Convergence

- **Status:** Proposed
- **Date:** 2026-05-26
- **Decision Owners:** DSX-Connect Architecture
- **Related:** ADR-003 (Enumeration and Jobs), ADR-007 (Reader Contract), ADR-013 (Tunable Recovery Granularity and Transaction Outbox)

## Context

DSX-Connect supports two important asynchronous repository protection modes:

- **full scan**
  - baseline traversal of existing content
- **monitored scan**
  - scan triggered by new or changed content events
  - also described operationally as `on-access scan` or `on-demand scan` depending on the integration surface

Repositories are often mutable during scan execution:

- files may be created during enumeration
- files may be updated after enumeration but before read
- files may be deleted before read
- files may be updated after scan completes

This means a full scan is not automatically a point-in-time snapshot.

In many connector models, enumeration and read happen over time against a live dataset. A connector may opportunistically see some newly created files during enumeration, but unless explicitly designed otherwise, there is no guarantee that all changes during scan execution are included.

The architecture therefore needs an explicit consistency model so operators and downstream policy do not assume stronger guarantees than the system actually provides.

## Decision

DSX-Connect will treat **full scan** as **baseline coverage over a live dataset**, not as a guaranteed point-in-time snapshot, unless a specific integration explicitly supports snapshot semantics.

DSX-Connect will treat **monitoring** as the **convergence mechanism** for changes that occur during or after the baseline scan.

The intended protection model is:

- **full scan only**
  - best-effort baseline coverage over a changing repository
- **monitoring only**
  - ongoing coverage for new or changed content after monitoring is active
- **full scan + monitoring**
  - baseline plus convergence for changes that occur during and after the baseline pass

Full scans establish baseline coverage across a repository at a point in operational time.

Because protected repositories remain active during scanning, full scans should be treated as best-effort enumeration of a live data set rather than immutable point-in-time snapshots.

Continuous monitoring or event-driven protection maintains convergence by detecting:

- newly created objects
- modified objects
- overwritten objects
- post-scan changes

## Decision Drivers

- avoid claiming snapshot guarantees that connectors cannot actually provide
- make repository mutation during scans a first-class architectural concern
- align expectations between operators, connectors, and policy
- preserve a clean model where monitoring closes the gap left by live full scans
- support version-aware handling when enumerated state and read-time state differ

## Clarifying Principle

A normal full scan is a **live traversal**, not a frozen-world replay.

Unless the source platform explicitly offers snapshot semantics and the connector implements them, DSX-Connect should assume:

- enumeration time and read time may observe different content states
- newly created objects may or may not be included in the same full scan
- objects scanned earlier may be modified later and become stale relative to the original baseline result

## Modes and Guarantees

## 1. Full Scan Only

Expected behavior:

- scans content encountered during the baseline traversal
- does not guarantee that all later updates are covered
- does not guarantee that files created after enumeration has passed their location are included

Implications:

- if a file is updated after it was scanned, that updated content may not be scanned until a later event or later full scan
- if a file is deleted before read, the system should record a read-time missing outcome rather than treat it as an impossible state

## 2. Monitoring Only

Expected behavior:

- detects new or changed content after monitoring is active
- does not provide baseline coverage for already existing content that does not change

Implications:

- monitoring-only is insufficient as a baseline protection strategy for existing repositories

## 3. Full Scan + Monitoring

Expected behavior:

- full scan provides initial broad coverage of the current corpus
- monitoring covers changes and arrivals that occur during and after the full scan window

This is the recommended steady-state model for mutable repositories.

## Consistency Outcomes

When possible, DSX-Connect should distinguish these cases explicitly:

### Enumerated and Read Same Version

- normal case
- read content matches enumerated version metadata

### Changed Before Read

- object was enumerated in one state
- reader observed a later state at read time

Recommended handling:

- record the version mismatch
- decide by policy whether to:
  - scan the newer version and record the mismatch
  - requeue under updated-object semantics
  - mark for follow-up

### Deleted Before Read

- object was enumerated
- object no longer exists when read is attempted

Recommended handling:

- classify as read-time missing or not-found-at-read
- do not pretend baseline coverage succeeded

### Changed After Scan

- object was scanned successfully
- object changed later

Handling:

- this is not recoverable by the already completed full-scan pass alone
- monitoring is the intended mechanism to detect and rescan the changed content

## Version-Aware Identity

Connectors should provide source-version metadata whenever possible.

Examples:

- etag
- version id
- generation number
- last modified timestamp
- provider revision identifier
- content hash if available

DSX-Connect should persist enough of this metadata to compare:

- enumerated version
- read version
- scanned version basis

This becomes more important when:

- reads are delayed
- batches are replayed after restart
- monitoring and full scan overlap

## Monitoring Convergence

The preferred architecture is convergence, not snapshot illusion.

Conceptually:

1. start full scan
2. establish a monitoring or change-tracking watermark where the platform supports it
3. run baseline enumeration and scan
4. process changes since the watermark
5. continue in normal monitored mode

Where supported, connectors should use:

- delta tokens
- change tokens
- event cursor watermarks
- provider-native revision checkpoints

This is the cleanest way to reduce the consistency gap between baseline and monitoring.

## Connector Contract Implications

Connectors should not promise snapshot guarantees unless they truly provide them.

Connector expectations:

- may opportunistically include some newly created files during enumeration
- must not imply complete inclusion of repository mutations during a full scan unless designed to do so
- should expose version/change metadata where the source platform permits it
- should support monitoring/convergence capabilities wherever practical

## Reader and Recovery Implications

Reader-native access improves hot-path performance but does not change the consistency model by itself.

A faster reader:

- reduces the time between enumeration and read
- may reduce, but does not eliminate, mutation windows

Recovery/replay also interacts with consistency:

- replayed work may read a later version than originally enumerated
- coarse-grained recovery is more acceptable when version-aware handling exists

## Data Model Implications

Recommended execution metadata additions:

- enumerated version metadata
- read-time version metadata
- scan basis metadata
- optional mismatch classification such as:
  - `version_changed_before_read`
  - `deleted_before_read`

This metadata should be visible enough for:

- operators
- policy debugging
- audit
- replay planning

## Operational Guidance

Honest platform statement:

- a normal full scan is best-effort baseline coverage over a live dataset
- monitoring provides convergence for later changes
- snapshot guarantees require connector-specific support and should be called out explicitly when available

Operational recommendation:

- full scans are recommended during lower repository activity when possible
- monitoring should remain enabled for steady-state protection
- protection coverage is achieved through the combination of baseline scanning and continuous monitoring
- for mutable repositories, prefer full scan plus monitoring
- do not rely on full scan alone for continuous protection of changing content

## Non-Goals

- not forcing every connector to implement snapshot semantics
- not requiring a globally frozen repository view where the source platform cannot provide one
- not treating opportunistic inclusion of newly discovered files as a formal contract

## Summary

DSX-Connect should explicitly model full scans as live baseline traversals and monitoring as the convergence mechanism for repository change.

That gives the architecture a truthful consistency model:

- baseline coverage from full scan
- ongoing change coverage from monitoring
- version-aware handling when enumerated content and read content diverge
