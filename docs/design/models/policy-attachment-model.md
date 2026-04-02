# Policy Attachment Model

## Purpose

This document defines where policy attaches in the DSX-Connect architecture.

The goal is to keep policy assignment clear, consistent, and unambiguous.

---

## Core Principle

Policy should attach to the **protected scope**, not to the connector implementation itself.

This follows from the architectural rule that:

- the integration is the platform connection
- the protected scope is the protection boundary

---

## Why Policy Should Not Attach to the Connector

If policy is attached to the connector directly:

- one integration with many content areas becomes hard to manage
- different areas with different risk tolerance cannot be modeled cleanly
- reporting and ownership become blurred
- connector configuration becomes overloaded with control-plane concerns

---

## Recommended Attachment Points

### Primary Attachment Point: Protected Scope

Policy should normally be attached at the protected scope level.

Examples:
- S3 `finance/` has stricter policy than `marketing/`
- SharePoint legal library requires hold/manual review
- HR onboarding folder allows only clean and scannable content

---

### Possible Secondary Attachment Points

These may exist later, but should not override the clarity of scope ownership:

- tenant defaults
- application defaults for inline clients
- content-type rules
- workflow rules

These should compose cleanly, not create ambiguous precedence.

---

## Policy Outcome Model

A policy should be able to produce normalized outcomes such as:

- allow
- block
- quarantine
- hold_for_review
- allow_with_audit_flag
- skip with reason, where explicitly configured

The connector should not choose these outcomes.
Core should evaluate policy and decide.

---

## Example

### SharePoint Integration

Integration:
- M365 tenant connection

Protected scopes:
- HR Documents
- Legal Contracts
- Marketing Assets

Policy:
- HR Documents → quarantine malicious, hold unknown
- Legal Contracts → hold suspicious/unscannable
- Marketing Assets → allow clean, quarantine malicious

Same integration, different protected-scope policies.

---

## Inline Use Case

For inline upload flows, policy may attach to an application-facing logical scope such as:

- tenant + application + upload channel
- tenant + business process
- tenant + content class

This is conceptually similar to protected scope, even if no repository object exists yet.

That suggests the long-term policy model should support both:

- repository protected scopes
- application logical scopes

through a shared abstraction.

---

## Open Questions

- Do we need a single abstraction above both repository scope and inline app scope?
- How expressive should policy be in the first version?
- How are manual review and workflow routing represented?
- Should policy be purely declarative, or partly procedural?

---

## Current Direction

Policy should attach where ownership is clear and object membership is unambiguous.

Today, that means:
- protected scopes for repository scanning
- likely application logical scopes for inline scanning