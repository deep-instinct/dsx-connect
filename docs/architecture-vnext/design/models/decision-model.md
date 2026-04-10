Yes—that’s an important correction. DSX-Connect isn’t just “scan → decide,” it’s:

> **multi-signal decisioning + orchestration**

So the decision model should reflect:

* DSXA (malware detection)
* DIANNA (threat intel / enrichment)
* future signals (DLP, classification, etc.)
* policy combining all of the above

Let’s capture that properly.

---

# `/design/models/decision-model.md`

````markdown
# Decision Model (Multi-Signal Evaluation & Orchestration)

## Purpose

This document defines how DSX-Connect evaluates files and produces decisions using multiple signals, not just malware scanning.

DSX-Connect acts as a **decision orchestration engine**, combining:

- malware detection (DSXA)
- threat intelligence (DIANNA)
- contextual signals
- policy rules

---

## Core Principle

DSX-Connect does not rely on a single signal.

It evaluates:

> multiple independent signals → normalized → combined via policy → final decision

---

## Signal Sources

### 1. Malware Detection (DSXA)

Primary signal source.

Provides:
- malicious / clean classification
- model confidence
- threat classification (where available)

---

### 2. Threat Intelligence (DIANNA)

External intelligence enrichment.

Provides:
- known bad indicators
- reputation data
- zero-day / emerging threat signals
- file hash intelligence

---

### 3. Contextual Signals

Derived from request or environment:

- tenant
- application
- logical scope
- protected scope
- file type
- file size
- user context (optional)

---

### 4. Future Signals (Extensible)

The model should support additional signals:

- DLP classification
- content classification (PII, sensitive data)
- behavioral signals
- external enrichment services

---

## Signal Normalization

Each signal source may produce different outputs.

DSX-Connect must normalize them into a consistent internal representation.

---

### Example Normalized Signal

```json
{
  "source": "dsxa",
  "type": "malware",
  "classification": "malicious",
  "confidence": 0.98
}
````

```json
{
  "source": "dianna",
  "type": "threat_intel",
  "classification": "known_bad",
  "confidence": 0.95
}
```

---

## Evaluation Pipeline

### Step 1: Ingest

* receive file or reference
* collect context

---

### Step 2: Signal Collection

* invoke DSXA
* query DIANNA (if applicable)
* gather contextual signals

---

### Step 3: Normalize

* convert all signals into unified structure

---

### Step 4: Policy Evaluation

Policy evaluates:

* signal classifications
* confidence levels
* context

Produces:

* final decision
* reason
* optional workflow actions

---

### Step 5: Decision Output

Return:

* verdict (normalized classification)
* decision (action)
* reasoning
* metadata

---

## Verdict Model

Verdict represents the **security classification**.

Suggested normalized set:

* malicious
* clean
* suspicious
* unknown

Verdict may be derived from multiple signals.

---

## Decision Model

Decision represents the **action to take**.

Canonical set:

* allow
* block
* quarantine
* hold_for_review

---

## Separation of Concerns

* **Signals → what is true about the file**
* **Verdict → summarized classification**
* **Decision → what to do about it**

---

## Example

### Case: Known Malware

Signals:

* DSXA → malicious
* DIANNA → known_bad

Verdict:

* malicious

Decision:

* block

---

### Case: Unknown but Suspicious

Signals:

* DSXA → unknown
* DIANNA → suspicious

Verdict:

* suspicious

Decision:

* hold_for_review

---

### Case: Clean but Policy Restricted

Signals:

* DSXA → clean
* DIANNA → clean

Context:

* file type restricted by policy

Verdict:

* clean

Decision:

* block (policy-driven)

---

## Conflict Handling

Signals may disagree.

Examples:

* DSXA = clean
* DIANNA = known_bad

Policy must define precedence or combination rules.

Options:

* strict (any bad signal → block)
* weighted scoring
* source priority (e.g., DIANNA overrides)

---

## Confidence Handling

Confidence may influence:

* decision thresholds
* escalation to hold/manual review
* audit flags

---

## Extensibility

The model must support:

* adding new signal sources
* evolving classification schemes
* plugin-style enrichment

without breaking API contracts

---

## Relationship to Policy Model

Policy defines:

* how signals are interpreted
* how conflicts are resolved
* what actions are taken

Decision model provides the inputs to policy.

---

## Relationship to API Model

The API exposes:

* verdict
* decision
* reason

but does not expose full internal signal graph unless requested.

---

## Open Questions

* Do we expose raw signals via API (debug mode)?
* How do we version signal schemas?
* Should we support scoring vs rule-based evaluation?
* How do we explain decisions for audit/compliance?

---

## Current Direction

DSX-Connect should act as:

> a multi-signal decision orchestration engine

not just a malware scanner wrapper.

This enables:

* richer decisions
* future extensibility
* stronger enterprise value

````

