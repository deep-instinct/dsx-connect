# Object Identity Model

## Purpose

This document defines how DSX-Connect should think about object identity across integrations and protected scopes.

A strong identity model is required for:

- deduplication
- idempotency
- remediation targeting
- event correlation
- job tracking
- reporting

---

## Identity Goals

The object identity model should allow DSX-Connect to answer:

- What exact object is this?
- Is this the same object seen before?
- Is this the same logical object but a different version?
- Which protected scope owns this object?
- Can this object be safely re-fetched or remediated?

---

## Identity Layers

### 1. Integration Identity

Identifies the integration instance through which the object is known.

Example:
- SharePoint tenant integration A
- S3 production integration B

This matters because the same apparent path in two different integrations is not the same object.

---

### 2. Scope Identity

Identifies the protected scope that owns the object.

This is the protection boundary and reporting boundary.

---

### 3. Logical Object Identity

Represents the stable logical object within the platform.

Examples:
- S3 bucket + key
- SharePoint drive ID + item ID
- GCS bucket + object name
- OneDrive drive ID + item ID

This should remain stable across repeated discovery of the same object.

---

### 4. Object Version Identity

Represents a specific version or change state of the object.

Examples:
- etag
- generation number
- version ID
- modified timestamp + size fallback when better version markers do not exist

This is necessary because the same logical object may be rescanned after modification.

---

## Recommended Identity Shape

A practical identity model should include:

- `integration_id`
- `scope_id`
- `platform_type`
- `platform_object_id`
- `platform_version_id` or equivalent
- `locator`

Optional:
- parent container identifiers
- canonical path
- display path

---

## Identity Semantics

### Same logical object, same version
Treat as the same scan target for idempotency purposes.

### Same logical object, new version
Treat as a new scan target.

### Same apparent path, different integration
Treat as different objects.

### Same object visible through two scopes
This should not happen. Scope overlap should be prevented by configuration validation.

---

## Why Path Alone Is Not Enough

Paths are useful for display, but often not sufficient as identity because:

- objects may be renamed
- platforms expose stable internal IDs
- different APIs may return slightly different paths
- path may not encode version

Whenever available, DSX-Connect should prefer platform-native stable IDs over display paths.

---

## Open Questions

- What is the minimum acceptable version signal on weak platforms?
- How should we represent identity for inline uploads before platform storage exists?
- Should DSX-Connect mint an internal canonical object identity string?

---

## Current Direction

DSX-Connect should treat identity as:

- integration-qualified
- scope-qualified
- logically stable
- version-aware