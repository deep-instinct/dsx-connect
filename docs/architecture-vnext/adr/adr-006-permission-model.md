# ADR-006: Granted Permission Model for Connector Integrations

## Status

Proposed

---

## Context

Connector integrations require access to external platforms such as:

* AWS S3
* SharePoint / OneDrive
* Google Cloud Storage
* file systems and enterprise repositories

Historically, integration approaches often involve:

* modifying platform configurations
* attaching policies directly to assets
* creating or overwriting event notifications
* deploying platform-side components (e.g., Lambda)

These approaches can:

* interfere with existing customer configurations
* create unintended side effects
* introduce operational risk
* blur ownership boundaries

---

## Decision

DSX-Connect will adopt a **Granted Permission Model**:

> Connectors must operate using permissions explicitly granted to them, not by modifying or taking control of platform configurations.

---

## Core Principle

DSX-Connect does not take permission.

It is **given permission**.

---

## Implementation Model

### Credentials-Based Access

Connectors should operate using credentials provided by the customer:

#### Examples

* AWS:

    * IAM role
    * access keys
    * cross-account role assumption

* Microsoft 365:

    * app registration
    * client ID + client secret
    * delegated or application permissions via Graph API

* Google Cloud:

    * service account JSON
    * scoped IAM roles

These credentials define:

* what DSX-Connect can read
* what it can write or modify (if allowed)
* what actions it is authorized to perform

---

## Connector Responsibilities Under This Model

Using granted permissions, connectors may:

* enumerate content
* read object metadata
* fetch file content
* apply remediation actions (if authorized)
* subscribe to existing signals where possible

They must not:

* modify unrelated platform configuration
* escalate their own privileges
* assume exclusive control over shared resources

---

## Separation of Concerns

### Customer / Platform Owner

Responsible for:

* defining IAM roles or permissions
* granting access to DSX-Connect
* managing platform configuration

---

### DSX-Connect

Responsible for:

* using granted permissions
* making security decisions
* orchestrating scanning and workflows
* auditing actions taken

---

## Benefits

### Non-Destructive Integration

* avoids overwriting configuration
* prevents disruption of existing systems

---

### Clear Ownership Boundaries

* customer owns infrastructure
* DSX-Connect owns security decisions

---

### Improved Security Posture

* follows least-privilege principles
* easier to audit and validate access

---

### Easier Adoption

* aligns with enterprise security expectations
* reduces friction in onboarding

---

## Tradeoffs

* requires customers to provision credentials correctly
* may limit capabilities where permissions are insufficient
* may require documentation and tooling to guide setup
* onboarding may be slightly more complex

---

## Relationship to Monitoring

Under this model:

* monitoring should rely on:

    * existing event systems
    * shared or additive integrations
    * polling where necessary

DSX-Connect should not require:

* replacing event configurations
* taking ownership of notification pipelines

---

## Example: AWS S3

Preferred model:

* customer grants DSX-Connect IAM role access
* DSX-Connect:

    * lists buckets
    * enumerates objects
    * reads content
    * optionally writes tags or moves objects

Avoid:

* modifying bucket notification configurations directly
* overwriting existing event pipelines

---

## Example: SharePoint / OneDrive

Preferred model:

* customer registers application in Azure AD
* grants API permissions via Microsoft Graph
* provides client credentials to DSX-Connect

DSX-Connect:

* reads files
* enumerates sites and drives
* applies actions where authorized

---

## Open Questions

* Should DSX-Connect provide automated setup tooling (e.g., Terraform, scripts)?
* How do we validate permissions during onboarding?
* Should we support multiple permission tiers (read-only vs full remediation)?
* How do we handle environments where granted permissions are insufficient for monitoring?

---

## Relationship to Other ADRs

* ADR-005 (Asset Protection and Configuration)
  → defines non-destructive integration principle

* ADR-002 (Tenant Connectors)
  → defines scope ownership within integrations

* ADR-001 (Security Hub)
  → reinforces DSX-Connect as decision plane, not infrastructure owner

---

## Current Direction

DSX-Connect should operate as:

> a security service that is **granted controlled access to platforms**, rather than one that **modifies and takes ownership of them**

This aligns with:

* enterprise security best practices
* least privilege access models
* modern SaaS integration patterns
