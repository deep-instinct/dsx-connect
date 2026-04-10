# DSX-Connect Architecture Overview

## Security Hub for File Risk Decisions

---

## Executive Summary

Modern enterprises face a fundamental challenge:

> Files enter systems from everywhere, but security decisions are fragmented, inconsistent, and often too late.

DSX-Connect addresses this by acting as a **central Security Hub** for file risk decisions.

* **File Scanning as a Service (FSaaS)**
* **Multi-signal decisioning (DSXA + intelligence + context)**
* **Unified policy and audit**
* **Inline + asynchronous workflows**

> **Any file. Anywhere. One decision.**

---

## The Core Shift

**From:** connect scanning into platforms
**To:** provide file security as a service

---

## Architecture Overview

```mermaid
flowchart LR
    A[Native Applications] --> H[DSX-Connect Security Hub]
    B[Connector Integrations] --> H
    H --> S[DSXA Malware Detection]
    H --> T[DIANNA Threat Intelligence]
    H --> P[Policy Engine]
    H --> D[Decision Engine]
    H --> W[Workflow / Audit / Jobs]

    B --> B1[Discovery]
    B --> B2[Enumeration]
    B --> B3[Monitoring]
    B --> B4[Fetch / Remediation]
```

### 1. Security Hub (Core)

* DSXA malware detection
* Threat intel enrichment (e.g., DIANNA)
* Policy evaluation & decisioning
* Audit, workflow, job lifecycle

---

### 2. Integration Patterns

```mermaid
flowchart TD
    H[DSX-Connect Security Hub]

    subgraph N[Native Application Integrations]
        N1[App receives file]
        N2[Call inline scan API]
        N3[App enforces decision]
        N1 --> N2 --> N3
    end

    subgraph C[Connector Integrations]
        C1[Discovery<br/>What can be protected?]
        C2[Enumeration<br/>What is in a scope?]
        C3[Monitoring<br/>What changed?]
        C4[Fetch / Remediation]
        C1 --> C2
        C2 --> C4
        C3 --> C4
    end

    N2 --> H
    C2 --> H
    C3 --> H
```

#### A. Native Application Integrations (Inline)

* Real-time, “scan before store”
* App calls `/scan`, enforces decision

#### B. Connector Integrations (Repository / Platform)

* Discovery, enumeration, monitoring
* Fetch/scan and remediation
* Async, large-scale, existing content + new content landing on repo

---

### 3. Shared Decision Plane

* Same scan engine, policy, decisions, audit across all paths

---

## Multi-Signal Decision Engine

```mermaid
flowchart LR
    F[File / Reference] --> G[Signal Collection]
    G --> X[DSXA]
    G --> I[DIANNA]
    G --> C[Context]

    X --> N[Normalize]
    I --> N
    C --> N

    N --> P[Policy]
    P --> D[Decision]
    D --> O[Allow / Block / Quarantine / Hold]
```

* **Verdict**: malicious / clean / suspicious / unknown
* **Decision**: allow / block / quarantine / hold

---

## Connector Model (Refined)

```mermaid
flowchart TD
    A[Connector Integration]

    A --> D[Discovery]
    A --> E[Enumeration]
    A --> M[Monitoring]

    D --> D1[What can be protected?]
    E --> E1[What exists now?]
    M --> M1[What changed?]

    D --> S[Protected Scopes]
    E --> J[Async Jobs]
    M --> J
```

* **Discovery** → define scopes
* **Enumeration** → baseline/bulk
* **Monitoring** → changes over time

> Connectors describe the platform. Core decides.

---

## Execution Flows

### Inline (Synchronous)

```mermaid
sequenceDiagram
    participant U as User
    participant A as App
    participant H as DSX-Connect
    participant X as DSXA
    participant I as DIANNA
    participant P as Policy

    U->>A: Upload
    A->>H: /scan
    H->>X: Scan
    X-->>H: Result
    H->>I: Enrich
    I-->>H: Intel
    H->>P: Evaluate
    P-->>H: Decision
    H-->>A: Verdict + Decision
    A-->>U: Enforce
```

### Connector / Repository (Async)

```mermaid
sequenceDiagram
    participant R as Repository
    participant C as Connector
    participant H as DSX-Connect
    participant X as DSXA
    participant I as DIANNA
    participant P as Policy

    R-->>C: Event / Content
    C->>H: Submit item
    H->>X: Scan
    X-->>H: Result
    H->>I: Enrich
    I-->>H: Intel
    H->>P: Evaluate
    P-->>H: Decision
    H->>C: Action
    C->>R: Remediate
```

---

## Protected Scope Model

* Non-overlapping scopes
* Each object belongs to exactly one scope
* Policy attaches at scope (or logical app scope)

---

## Why This Matters

* **Consistency**: one decision model
* **Scalability**: inline + async
* **Flexibility**: apps + platforms
* **Extensibility**: new signals
* **Control**: centralized policy/audit

---

## Positioning

> **Security Hub for file risk decisions**
> **Multi-signal decision engine**
> **File Scanning as a Service**

---

## Closing

> **Any file. Anywhere. One decision.**
