# ADR-010: Tiered Credential Strategy Support and Preferred Dynamic Identity Model

* **Status:** Proposed
* **Date:** 2026-04-10
* **Related:** ADR-007 (Reader Model), ADR-008 (Capability Model), ADR-009 (Brokered Credential Delivery)

---

## Context

ADR-009 establishes that DSX-Connect will use a **brokered credential model**, where workers obtain short-lived execution credentials at runtime using an access-context reference.

However, real-world customer environments vary significantly in how they provide access to platforms such as AWS, Azure, GCP, and SaaS applications:

* some customers use static credentials (e.g., AWS access keys, Azure client secrets)
* others use rotated or brokered secrets (e.g., Vault)
* more mature environments use identity-based access (e.g., IAM roles, managed identity, workload identity)

DSX-Connect must support this range of environments while still guiding toward a secure and scalable architecture.

---

## Decision

DSX-Connect will support a **tiered credential strategy model**, allowing multiple credential mechanisms per integration, while standardizing on **short-lived, identity-based access** as the preferred execution model.

Each integration will declare its supported credential strategies, and DSX-Connect will:

* support lower-tier strategies for compatibility
* prefer higher-tier strategies when available
* align runtime execution (ADR-009) to always use short-lived access, regardless of source strategy

---

## Core Principle

**Credential strategy is an integration concern. Execution access is a platform concern.**

* Connectors define *how access can be obtained*
* Core brokers *how access is used at runtime*
* Workers consume *only short-lived execution credentials*

---

## Credential Strategy Tiers

### Tier 1 — Static Credentials (Compatibility)

Examples:

* AWS access keys
* Azure client secrets
* GCP service account JSON keys

**Characteristics**

* long-lived
* manually rotated
* broad access scope
* widely supported

**Usage**

* supported for onboarding and compatibility
* stored securely by the platform
* used by the broker to derive runtime access where possible

**Limitations**

* larger blast radius if exposed
* operational overhead for rotation
* weaker execution-level auditability

---

### Tier 2 — Brokered / Rotated Credentials (Intermediate)

Examples:

* Vault-issued AWS credentials
* token refresh workflows
* centrally rotated secrets

**Characteristics**

* shorter-lived than static credentials
* centrally managed
* reduced exposure

**Usage**

* supported as an improvement over static credentials
* may be used directly or as input to brokered execution access

**Limitations**

* still secret-based
* does not fully eliminate credential handling

---

### Tier 3 — Dynamic / Identity-Based Access (Preferred)

Examples:

* AWS IAM role assumption (STS)
* Azure Managed Identity
* GCP Workload Identity / Service Account Impersonation

**Characteristics**

* no long-lived credentials stored
* short-lived tokens
* strong auditability
* least-privilege by design

**Usage**

* preferred integration model
* broker resolves execution access using identity and trust relationships
* aligns directly with ADR-009

**Benefits**

* minimizes credential exposure
* simplifies rotation
* aligns with cloud best practices
* enables fine-grained, capability-scoped access

---

## Integration Declaration

Each integration must declare supported credential strategies.

Example:

```
aws.s3:
  credential_strategies:
    - static_keys
    - assumed_role
    - workload_identity
```

This enables:

* onboarding validation
* dynamic capability checks
* future extensibility

---

## Runtime Behavior

Regardless of credential strategy:

* jobs do not carry secrets
* workers do not store long-lived credentials
* execution access is resolved at runtime via the broker

The broker may:

* use static credentials to assume a role
* exchange identity for tokens
* retrieve short-lived credentials from external systems

Workers only receive short-lived execution credentials.

---

## Platform Guidance

DSX-Connect should guide customers toward higher-tier strategies:

* allow static credentials for ease of onboarding
* encourage transition to identity-based models
* document preferred patterns per platform
* provide validation warnings for lower-tier strategies

---

## Benefits

### Flexibility

Supports a wide range of customer environments.

### Security Evolution Path

Provides a path from static → dynamic credential models.

### Consistency

Unifies execution behavior regardless of credential source.

### Alignment with Modern Practices

Matches cloud-provider recommendations.

### Integration Simplicity

Allows multiple strategies without changing worker logic.

---

## Tradeoffs

* increased implementation complexity
* broker must support multiple credential types
* additional documentation and onboarding guidance required

---

## Risks

* customers may remain on weaker credential strategies
* inconsistent implementation across integrations
* risk of over-scoped access if contracts are not strict

---

## Consequences

* integrations must declare credential strategies
* connectors validate strategy during onboarding
* broker supports multiple input types
* workers remain isolated from credential complexity

---

## Non-Goals

This ADR does not define:

* internal broker implementation details
* exact token exchange flows per platform
* UI/UX for onboarding

---

## Follow-On Work

1. define credential strategy schema and validation
2. define broker handling per strategy
3. document platform-specific patterns (AWS, Azure, GCP, SaaS)
4. define migration paths between tiers
5. implement auditing and reporting

---

## Summary

DSX-Connect will support a tiered credential strategy model to accommodate diverse customer environments while standardizing on dynamic, identity-based access as the preferred approach.

This enables compatibility, scalability, and alignment with modern cloud security practices, while ensuring all runtime execution uses short-lived, brokered credentials.

