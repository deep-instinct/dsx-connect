# Scope Engine RFC

Status: Draft  
Owner: DSX-Connect Core  
Last Updated: 2026-03-26

## 1. Problem Statement

The existing connector-centric model couples platform integration, scope definition, filtering, and policy decisions inside connector deployments. This creates ambiguity, operational sprawl, and inconsistent behavior across platforms.

We need a core-owned protection model that is deterministic, scalable, and platform-consistent.

## 2. Decision Summary

### Shift from Connector-Centric to Core-Centric

Old model:
- Connector = integration + asset + filter + policy
- One connector instance per repository/site/bucket partition
- Deployment-time sharding defines protection boundaries

New model:
- Integration = platform connection
- Protected Scope = what to protect
- Policy = how to protect

Result:
- Core becomes policy/control plane
- Connectors become platform adapters

## 3. Target Model

### 3.1 Integration (Platform-Level)

One integration per platform boundary (AWS account, GCP project, M365 tenant, etc.).

Integration responsibilities:
- credentials/authentication
- connectivity health
- discovery capability
- monitoring capability

Integration explicitly does not own:
- asset selection
- filter evaluation
- scope/policy decisions

### 3.2 Protected Scope (Primary Object)

A protected scope is the core unit of protection.

Contains:
- resource locator (ID-based or path-based)
- filter definition
- scan mode (`full_scan`, `monitor`)
- remediation policy
- enabled/disabled

Managed by core API/UI; not deployment config.

### 3.3 No-Overlap Rule

Within a single integration:
- scopes cannot overlap
- no identical or ancestor/descendant collisions

Guarantee:
- each resource maps to exactly one scope
- no precedence/inheritance logic required

### 3.4 Clone, Not Inherit

Integrations may define defaults, but scope creation copies values.
No live inheritance after creation.

## 4. Connector vs Core Responsibilities

### Connector (Adapter/Data Plane)

Connectors:
- authenticate with platform
- discover resources
- normalize identities/events
- ingest platform events
- manage platform subscriptions/watchers lifecycle
- emit normalized events to core

Connectors do not:
- evaluate filters
- resolve scope membership
- decide scan/remediation policy

### Core (Policy Engine)

Core:
- stores scopes and policies
- validates no-overlap
- matches events/resources to scope
- evaluates filters
- deduplicates events
- routes scans
- applies remediation

## 5. Identity Model and Durability

### Principle

Use strongest available identity.

### ID-Based Platforms (SharePoint/OneDrive-style)

Use stable IDs (site/drive/item).
Paths are display metadata.

Durability:
- rename: scope persists
- move: scope persists if stable ID unchanged

### Path-Based Platforms (S3/GCS prefixes/filesystem)

Use canonical path/prefix locators.

Durability:
- rename: scope breaks
- move: treated as new location (copy/delete semantics)

## 6. Object Storage Semantics

For S3/GCS/Azure:
- bucket/container is durable root identity
- prefix is selector, not first-class durable object identity

Scopes should be modeled as:
- bucket/container + optional filter/path selector

## 7. Monitoring Model

Split responsibilities:

Core (control plane):
- computes monitoring intent from enabled monitor scopes

Connector (data plane):
- creates and maintains platform subscriptions/watchers
- renews/reconciles bindings
- reports health/errors

Important distinction:
- scope granularity = policy boundary
- monitoring granularity = platform constraint

## 8. Coverage Model

In addition to explicit scopes, core supports coverage mode per integration:
- protect all containers of a type
- apply explicit container exclusions

Examples:
- all buckets except `logs-bucket`
- all mailboxes except service accounts
- all sites except selected sites

Constraints:
- coverage is container-level only
- no sub-container partial coverage rules
- no overlap ambiguity with explicit scopes

## 9. Mail/Teams/OneDrive Application

DSX-Connect remains file-scanning focused.

### OneDrive

Same semantics as SharePoint-style file model (ID-based where available).

### M365 Mail

- carrier object: message/mailbox/folder
- scan object: attachment file
- do not scan message body/chat text

### Teams

- carrier object: channel/thread/message context
- scan object: file/attachment
- do not scan conversation text

Attachment identity must retain parent context for auditability:
- mailbox/team/channel/message identifiers
- attachment identifier

## 10. Matching and Performance Requirements

Critical runtime question:
- Which scope does this resource/event belong to?

Must remain low-latency under high event volume.

Required behavior:
- deterministic (0 or 1 scope)
- fast lookup
- write-time overlap validation
- runtime filter evaluation after scope match

## 11. Minimal Data Model

- `integrations`
- `protected_scopes`
- `scope_locators`
- `scope_policies`
- optional `coverage_rules` (per integration)
- optional denormalized in-memory match index

## 12. Event Contract

Connector -> Core normalized event must include:
- `integration_id`
- platform
- stable resource identity (or canonical path)
- container context
- event metadata (type, time, source cursor/sequence)
- schema version

## 13. Rollout Strategy

- dual-path shadow mode (legacy + new matcher)
- diff-only metrics initially
- pilot per integration
- cutover by feature flag
- rollback: disable new scope engine routing, keep ingestion intact

Reference runbook: `docs/architecture-vnext/rfc/scope-engine-migration-checklist.md`

## 14. Non-Goals

Out of scope for this RFC:
- message body/content scanning
- replacing connector transport plumbing in one step
- platform-specific UI design details

## 15. Open Questions

1. Unified indexing strategy for explicit scopes + coverage exclusions at scale.
2. Conflict policy between explicit scope and coverage include/exclude if both configured.
3. Scope evolution tooling for legacy connector configs.
4. Cross-platform canonical identity representation standard.

## 16. Success Criteria

- connectors no longer evaluate scope/filter/policy
- no-overlap validation enforced in core
- deterministic scope match behavior in production
- reduced connector deployment sharding complexity
- stable event-to-scan throughput at target scale
