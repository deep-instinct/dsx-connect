# ADR-002: Tenant Connectors and Protected Scope Model

## Status

Proposed

## Context

Current connector design tends toward:

* One connector per repository/site/bucket
* Connector owns asset + filtering logic
* Limited flexibility for multi-scope environments

This creates issues:

* Operational sprawl (many connectors per tenant)
* Overlapping or unclear scope boundaries
* Difficulty scaling across large environments (e.g., many SharePoint sites or S3 buckets)

We need a model that:

* Scales to large enterprise environments
* Enforces clear ownership of objects
* Avoids ambiguity and overlap
* Keeps connectors simple

---

## Decision

Adopt a **Tenant Integration + Protected Scope model**:

### Core Principles

* A **connector represents an integration with a platform**

    * Example: SharePoint, S3, GCS

* Within an integration, define **multiple protected scopes**

* **Protected scopes must not overlap**

    * Each object belongs to exactly one scope

* No inheritance or precedence between scopes

---

## Model

### Integration (Connector Instance)

Represents:

* Platform connection
* Credentials / auth
* API interaction

Example:

* SharePoint integration for a tenant
* S3 integration for an account

---

### Protected Scope

Represents:

* A defined subset of content within the integration

Examples:

* Specific bucket
* Specific prefix
* Specific SharePoint site/library

Rules:

* Non-overlapping
* Explicit boundaries
* Independently policy-controlled

---

## Responsibilities

### Connector

* Discovers/enumerates objects
* Provides batches + cursor
* Supplies metadata + identifiers
* Does NOT enforce policy

---

### Core (DSX-Connect)

* Assigns objects to scopes
* Enforces non-overlap guarantees
* Applies policy
* Tracks job state and counts

---

## Consequences

### Positive

* Clear ownership of every object
* Scales cleanly across large environments
* Simplifies connector logic
* Enables consistent policy application

### Tradeoffs

* Requires strong validation of scope definitions
* May require migration from existing connector configs
* Users must understand scope boundaries

---

## Open Questions

* How are scopes defined (UI, config, API)?
* How do we validate non-overlap efficiently?
* How do we handle dynamic environments (new buckets/sites)?
* Should “catch-all” scopes exist?

---

## Notes

* This model aligns with the shift toward DSX-Connect as a **control plane**
* Connectors become **data providers**, not decision-makers
