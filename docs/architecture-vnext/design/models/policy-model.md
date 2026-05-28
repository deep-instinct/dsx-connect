Perfect—this is the last core piece that turns everything into a **real, programmable system**.

---

# `/design/models/policy-model.md`

````markdown
# Policy Model (Decision Rules & Orchestration)

## Purpose

This document defines how policies are structured and evaluated in DSX-Connect.

For the runtime handoff between scan completion, policy evaluation, downstream stage enqueueing, and stage-specific result delivery, see:

- `design/models/post-scan-orchestration-model.md`
- `design/models/result-sink-model.md`

Policy is responsible for:

- interpreting signals (DSXA, DIANNA, etc.)
- applying contextual rules
- producing final decisions
- triggering workflows

For the connector-facing execution contract that applies after policy chooses remediation, see:

- `design/models/remediation-contract-model.md`

---

## Core Principle

Policy answers:

> “Given these signals and this context, what should we do?”

Policy is:

- centralized
- deterministic (given same inputs)
- independent of connectors and applications

In `dsx_connect_ng`, policy is currently modeled as a **local component invoked by scan completion**, not as a required queue hop.

The canonical runtime contract is:

- `PolicyHandoffRequest`
- `PolicyHandoffDecision`

The older `PolicyDecision` model remains only as a compatibility bridge for transitional worker paths.

---

## Runtime Config Sources

Policy input is expected to come from three layers:

1. integration runtime config
2. protected-scope `post_scan_policy`
3. per-item explicit overrides in the submitted item payload

The intended precedence is:

1. per-item explicit override
2. scope policy override
3. integration policy default
4. runtime fallback/default behavior

This keeps policy programmable without requiring the scan worker itself to own branching logic.

---

## Current Typed Runtime Policy Config

The current typed config surface is intentionally small and pragmatic.

Integration config may include:

```json
{
  "policy": {
    "policy_id": "default-policy",
    "auto_dianna_on_verdicts": ["malicious"],
    "wait_for_dianna_on_auto_request": true,
    "remediation_plan_by_verdict": {
      "malicious": { "action": "quarantine" }
    },
    "result_delivery_policy": {
      "scan": "malicious_only",
      "remediation": "all_outcomes",
      "dianna": "completed_only"
    },
    "delivery": {
      "scan_targets": [{ "connector": "scan-sink" }],
      "workflow_summary_targets": [{ "connector": "summary-sink" }]
    },
    "content_preservation_mode_by_verdict": {
      "malicious": "cached"
    }
  }
}
```

Protected scopes may provide the same policy shape through `post_scan_policy`, overriding integration defaults where specified.

This typed policy config should be validated at the control-plane boundary:

- integration `config`
- protected-scope `post_scan_policy`

Invalid policy config should fail on create/update rather than surfacing later during scan-time orchestration.

Current typed fields:

- `policy_id`
- `auto_dianna_on_verdicts`
- `wait_for_dianna_on_auto_request`
- `remediation_plan_by_verdict`
- `result_delivery_policy`
- `delivery.scan_targets`
- `delivery.remediation_targets`
- `delivery.dianna_targets`
- `delivery.workflow_summary_targets`
- `content_preservation_mode_by_verdict`

This is not yet a full rule engine. It is the first explicit, typed policy surface that drives the post-scan orchestration contract.

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
- integration runtime config
- protected-scope policy override
- current `content_source`
- current delivery requirements

In the current runtime, scan worker builds this into `PolicyHandoffRequest.policy_context` and `PolicyHandoffRequest.item_metadata` before invoking policy.

---

## Current Default Evaluation Behavior

Today’s default/stub policy engine applies these rules:

- per-item explicit `policyDecision` wins if provided
- otherwise resolved integration/scope policy config is consulted
- otherwise verdict-driven defaults apply

Current default behaviors include:

- malicious or suspicious verdicts may auto-request DIANNA if configured
- malicious or suspicious verdicts may map to a configured remediation plan
- stage-specific result emission policy may come from typed policy config
- content preservation may move to `cached` or other modes based on verdict
- delivery targets may differ by result family:
  - `scan_result`
  - `remediation_result`
  - `dianna_result`
  - `workflow_summary`

This keeps the scan worker thin:

- scan worker executes scan
- policy decides applicability, preservation, and result emission
- downstream side-effect workers execute only what policy requested

Policy decides remediation intent. Connectors should not reinterpret that intent from connector-local policy settings.

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
