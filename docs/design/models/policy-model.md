Perfect—this is the last core piece that turns everything into a **real, programmable system**.

---

# `/design/models/policy-model.md`

````markdown
# Policy Model (Decision Rules & Orchestration)

## Purpose

This document defines how policies are structured and evaluated in DSX-Connect.

Policy is responsible for:

- interpreting signals (DSXA, DIANNA, etc.)
- applying contextual rules
- producing final decisions
- triggering workflows

---

## Core Principle

Policy answers:

> “Given these signals and this context, what should we do?”

Policy is:

- centralized
- deterministic (given same inputs)
- independent of connectors and applications

---

## Inputs to Policy

Policy evaluates two categories of inputs:

### 1. Signals

From the Decision Model:

- malware classification (DSXA)
- threat intelligence (DIANNA)
- future signals (DLP, classification, etc.)

Each signal includes:
- source
- classification
- confidence

---

### 2. Context

Provided by request or system:

- tenant_id
- application_id
- logical_scope (inline)
- protected_scope (repository)
- content_type
- file size
- optional user/workflow metadata

---

## Policy Structure

A policy consists of:

- metadata
- rules
- default behavior

---

### Example Structure

```json
{
  "policy_id": "policy-hr-documents",
  "description": "HR document protection policy",
  "rules": [...],
  "default_action": "allow"
}
````

---

## Rule Model

Each rule consists of:

* conditions
* action
* optional priority

---

### Example Rule

```json
{
  "id": "block-malware",
  "priority": 100,
  "conditions": {
    "any": [
      { "signal": "dsxa.classification", "equals": "malicious" },
      { "signal": "dianna.classification", "equals": "known_bad" }
    ]
  },
  "action": {
    "decision": "block",
    "reason": "malware_detected"
  }
}
```

---

## Condition Model

Conditions should support:

### Logical Operators

* `any` (OR)
* `all` (AND)
* `not`

---

### Signal-Based Conditions

Examples:

```json
{ "signal": "dsxa.classification", "equals": "malicious" }
```

```json
{ "signal": "dianna.confidence", "greater_than": 0.9 }
```

---

### Context-Based Conditions

Examples:

```json
{ "context": "content_type", "equals": "application/exe" }
```

```json
{ "context": "logical_scope", "equals": "uploads" }
```

---

### Combined Conditions

```json
{
  "all": [
    { "signal": "dsxa.classification", "equals": "unknown" },
    { "context": "content_type", "equals": "application/pdf" }
  ]
}
```

---

## Action Model

Actions define what happens when a rule matches.

---

### Core Fields

* decision
* reason
* optional metadata

---

### Example

```json
{
  "decision": "hold_for_review",
  "reason": "suspicious_file"
}
```

---

## Decision Set (Canonical)

* allow
* block
* quarantine
* hold_for_review

---

## Rule Evaluation

### Priority-Based Evaluation

* rules evaluated in priority order (highest first)
* first matching rule wins

---

### Default Behavior

If no rules match:

* apply `default_action`

---

## Conflict Resolution

Conflicts are avoided by:

* priority ordering
* first-match semantics

Alternative models (future):

* scoring systems
* weighted evaluation

---

## Example Policy

```json
{
  "policy_id": "default-upload-policy",
  "rules": [
    {
      "id": "block-malware",
      "priority": 100,
      "conditions": {
        "any": [
          { "signal": "dsxa.classification", "equals": "malicious" },
          { "signal": "dianna.classification", "equals": "known_bad" }
        ]
      },
      "action": { "decision": "block" }
    },
    {
      "id": "hold-suspicious",
      "priority": 50,
      "conditions": {
        "any": [
          { "signal": "dsxa.classification", "equals": "unknown" },
          { "signal": "dianna.classification", "equals": "suspicious" }
        ]
      },
      "action": { "decision": "hold_for_review" }
    }
  ],
  "default_action": "allow"
}
```

---

## Policy Attachment

Policies attach to:

* protected scopes (repository)
* logical scopes (inline applications)

This ensures:

* clear ownership
* no ambiguity
* consistent enforcement

---

## Workflow Integration

Policy may trigger workflows such as:

* manual review queue
* notification events
* audit flags
* remediation instructions

These should be:

* declarative where possible
* executed by core services

---

## Explainability

Policy should support:

* reason codes
* rule ID that triggered decision
* audit trace of evaluation

This is critical for:

* debugging
* compliance
* customer trust

---

## Extensibility

Policy model should support:

* new signal types
* new condition operators
* new decision types (if needed)
* plugin-based evaluation

---

## Open Questions

* Do we need a DSL instead of JSON?
* Should policies be versioned?
* How do we safely test policy changes?
* Do we support simulation / dry-run mode?
* How do we expose policy evaluation traces?

---

## Current Direction

Policy is the **decision brain** of DSX-Connect.

It:

* consumes normalized signals
* evaluates rules deterministically
* produces consistent decisions
* enables orchestration beyond scanning

This completes the model:

> Signals → Policy → Decision → Action

````
