# Integration and Protected Scope Model

## Purpose

This document defines how DSX-Connect models platform integrations and protected scopes.

This model supports a shift away from per-repository or per-site connectors toward platform integrations that can represent many protected areas within a tenant.

---

## Core Concepts

### Integration

An **integration** is a configured connection between DSX-Connect and an external platform.

Examples:
- AWS S3 integration
- Google Cloud Storage integration
- SharePoint integration
- OneDrive integration

An integration is responsible for:

- platform authentication
- API communication
- object discovery and enumeration
- object fetch/remediation operations where supported

An integration is **not** the policy boundary.

---

### Protected Scope

A **protected scope** is a specific subset of content inside an integration that DSX-Connect treats as a distinct protection boundary.

Examples:
- an S3 bucket
- a bucket prefix
- a SharePoint site
- a document library
- a folder subtree
- a OneDrive drive or folder subtree

A protected scope is responsible for:

- defining which objects belong to it
- serving as a policy attachment point
- serving as an operational and reporting boundary

---

## Core Rule: Non-Overlapping Scope Membership

Within a single integration:

- protected scopes must not overlap
- each object belongs to exactly one protected scope
- there is no inheritance or precedence between scopes

This avoids ambiguity in:

- policy assignment
- scan ownership
- remediation ownership
- counting and reporting

---

## Why This Model Exists

This model is intended to solve several problems:

- connector sprawl caused by one connector per repository/site/bucket
- unclear ownership when two configurations can “see” the same object
- inconsistent policy application
- difficulty scaling across large tenant environments

The goal is to make the integration the platform boundary and the protected scope the protection boundary.

---

## Examples

### Example: S3

Integration:
- AWS account + region + credentials

Protected scopes:
- `bucket-a/finance/`
- `bucket-a/hr/`
- `bucket-b/legal/`

Invalid example:
- `bucket-a/finance/`
- `bucket-a/finance/payroll/`

These overlap, so they cannot both exist as protected scopes in the same integration.

---

### Example: SharePoint

Integration:
- Microsoft 365 tenant + app registration

Protected scopes:
- Site A / Documents
- Site B / Contracts
- Site C / HR / Onboarding

Invalid example:
- Site A
- Site A / Documents / Legal

These overlap unless the model explicitly partitions the parent scope so the child is excluded.

---

## Scope Definition Requirements

A protected scope definition should be:

- explicit
- stable
- testable
- non-overlapping with all other scopes in the same integration

Each scope should have:

- a unique scope ID
- a platform-specific selector
- optional display name
- attached policy reference(s)
- status/health metadata

---

## Open Design Questions

- Should DSX-Connect support automatic partitioning of broader parent scopes?
- Should “catch-all” scopes exist for unmatched content?
- How should new content containers discovered after onboarding be handled?
- Should a scope be allowed to exist without policy, or should policy always be required?

---

## Current Direction

At this stage, DSX-Connect should treat:

- **integration** as the platform connection
- **protected scope** as the unit of ownership, policy, and reporting