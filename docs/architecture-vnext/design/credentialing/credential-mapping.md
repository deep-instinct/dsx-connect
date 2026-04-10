# Credential Strategy Mapping: Current vs Target State

* **Related:** ADR-009, ADR-010
* **Purpose:** Provide practical guidance for how DSX-Connect integrations should evolve from common credential patterns to the preferred architecture

---

## Overview

Most environments today rely on **static or semi-static credentials**.
DSX-Connect supports these for compatibility, but the **target state is always short-lived, identity-based access** resolved at runtime via the credential broker.

This document maps:

> **What customers typically have today → What DSX-Connect should move them toward**

---

# ☁️ AWS (S3, etc.)

## 🔴 Common Today (Tier 1)

```
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

Used via:

* IAM users
* long-lived credentials in config/env

**Problems**

* long-lived secrets
* manual rotation
* broad permissions
* hard to audit per execution

---

## 🟡 Transitional (Tier 2)

* Vault-issued AWS credentials
* rotated IAM user keys
* limited-lifetime keys

**Improvement**

* better rotation
* reduced exposure

---

## 🟢 Target State (Tier 3)

**IAM Role Assumption (STS)**

Flow:

1. Customer creates IAM Role with:

    * S3 read/enumerate/remediate permissions
    * trust relationship with DSX-Connect

2. DSX-Connect:

    * uses broker to call `AssumeRole`
    * receives short-lived credentials

3. Worker:

    * Reader uses temporary credentials
    * credentials expire automatically

---

## ✅ DSX-Connect Position

* support access keys (baseline)
* strongly recommend role assumption
* broker converts all strategies → STS creds at runtime

---

# ☁️ Azure (Blob, Data Lake, etc.)

## 🔴 Common Today (Tier 1)

* App Registration + Client Secret
* Storage account keys

**Problems**

* long-lived secrets
* manual rotation
* over-privileged access

---

## 🟡 Transitional (Tier 2)

* certificate-based auth
* rotated client secrets
* Key Vault-backed secrets

---

## 🟢 Target State (Tier 3)

**Managed Identity / Entra ID Token**

Flow:

1. DSX-Connect runs with:

    * Managed Identity (preferred)
      OR
    * App Registration with delegated trust

2. Broker:

    * obtains OAuth token from Entra ID

3. Worker:

    * Reader uses token to access Blob APIs

---

## ✅ DSX-Connect Position

* support client secrets (baseline)
* prefer managed identity wherever possible
* broker handles token acquisition

---

# ☁️ GCP (GCS, etc.)

## 🔴 Common Today (Tier 1)

* Service Account JSON key files

**Problems**

* long-lived keys
* key leakage risk
* manual rotation

---

## 🟡 Transitional (Tier 2)

* rotated service account keys
* Vault-managed keys

---

## 🟢 Target State (Tier 3)

**Workload Identity / Service Account Impersonation**

Flow:

1. DSX-Connect identity is allowed to:

    * impersonate target service account

2. Broker:

    * requests short-lived access token

3. Worker:

    * Reader uses token for GCS access

---

## ✅ DSX-Connect Position

* support JSON keys (baseline)
* strongly prefer impersonation
* eliminate long-lived keys where possible

---

# 🧩 SaaS Platforms (SharePoint, OneDrive, etc.)

## 🔴 Common Today

* App Registration + Client Secret
* tenant-wide permissions

---

## 🟢 Target State

**OAuth / App-Only Token (Brokered)**

Flow:

1. Connector:

    * establishes tenant consent

2. Broker:

    * obtains access token via OAuth

3. Worker:

    * Reader uses token for API access

---

## ⚠️ Notes

* no true “managed identity” equivalent
* broker is critical here
* scoping permissions is harder → must be enforced carefully

---

# 🧠 Key Architectural Insight

Across all platforms:

> **Static credentials are never the execution model — only an input into the broker.**

---

## Final Execution Pattern (Unified)

Regardless of platform:

1. Job created with:

    * `access_context_ref`

2. Worker:

    * requests execution credential from broker

3. Broker:

    * resolves using:

        * static creds → assume role / token exchange
        * identity → direct token
        * Vault → dynamic creds

4. Worker:

    * uses short-lived credential
    * discards after execution

---

# 🔥 DSX-Connect Positioning (This is important)

You now have a very strong, simple message:

> “We support your current credential model — but execute securely using short-lived access.”

---

# 🧭 Migration Guidance

DSX-Connect should guide customers along this path:

```
Static → Rotated → Identity-Based
```

Suggested approach:

* allow static onboarding
* surface warnings/recommendations
* provide docs + examples for upgrading
* make identity-based setup first-class

---

# 🚀 Summary

| Platform | Today (Common) | Target                 |
| -------- | -------------- | ---------------------- |
| AWS      | Access Keys    | AssumeRole (STS)       |
| Azure    | Client Secret  | Managed Identity       |
| GCP      | JSON Key       | Workload Identity      |
| SaaS     | Client Secret  | OAuth Token (Brokered) |

---

## Final Takeaway

The architecture does not force customers to change immediately.

But it ensures that:

* all execution uses short-lived credentials
* connectors stay out of the hot path
* workers scale cleanly
* security improves over time

---

```mermaid
sequenceDiagram
    autonumber

    participant C as Connector
    participant Core as Core / Credential Broker
    participant W as Scan Request Worker
    participant R as Reader
    participant P as Repository Platform
    participant D as DSXA

    Note over C,Core: Integration onboarding / trust establishment
    C->>Core: Register integration, capabilities, credential strategy
    Core-->>C: Integration accepted

    Note over Core,W: Scan job created
    Core->>W: Dequeue job with object context + access_context_ref + reader_type

    W->>Core: Request execution credential(access_context_ref, capability, scope)
    Core->>Core: Resolve credential strategy

    alt Static credential compatibility path
        Core->>P: Exchange stored credential / derive runtime access
        P-->>Core: Short-lived execution credential
    else Dynamic identity path
        Core->>P: Assume role / obtain token / impersonate identity
        P-->>Core: Short-lived execution credential
    else External broker path
        Core->>P: Request dynamic credential from external secret/identity system
        P-->>Core: Short-lived execution credential
    end

    Core-->>W: Return short-lived execution credential

    W->>R: Resolve Reader(reader_type)
    W->>R: Open stream(object context, execution credential)
    R->>P: Read object stream
    P-->>R: Object content stream
    R-->>W: Stream

    W->>D: Submit object stream for scanning
    D-->>W: Scan verdict / result

    W->>Core: Persist result / update state

```

The connector establishes trust and declares credential strategy, Core brokers runtime access, the worker resolves the Reader, and the Reader accesses the repository using short-lived execution credentials.

```mermaid
flowchart LR
    subgraph ControlPlane[Control Plane]
        C1[Connector]
        C2[Core]
        C3[Credential Broker]
    end

    subgraph DataPlane[Data Plane]
        D1[Generic Worker]
        D2[Reader Capability]
        D3[DSXA]
    end

    subgraph Platform[Protected Platform]
        P1[Repository / SaaS / Cloud Storage]
    end

    C1 -->|registers integration<br/>and credential strategy| C2
    C2 -->|creates job with<br/>access context ref| D1
    D1 -->|resolve reader| D2
    D1 -->|request execution credential| C3
    C3 -->|obtain short-lived access| P1
    C3 -->|return short-lived credential| D1
    D2 -->|read / enumerate / remediate| P1
    D1 -->|stream content| D3
    D3 -->|verdict| D1
    D1 -->|result/state update| C2
```

```mermaid
flowchart TD
    A[Integration Package Deployed] --> B[Connector Registers Integration]
    A --> C[Reader Registers Capability]

    B --> D[Core Stores Integration Metadata]
    C --> E[Worker Runtime Can Resolve Reader by Type]

    D --> F[Protected Scope Defined in Core]
    F --> G[Core Creates Scan Job]

    G --> H[Job Contains Object Context<br/>Reader Type<br/>Capability<br/>Access Context Ref]

    H --> I[Generic Worker Dequeues Job]
    I --> J[Worker Resolves Reader from Registry]
    I --> K[Worker Requests Execution Credential<br/>from Core Credential Broker]

    K --> L{Credential Strategy}
    L --> M[Static Credential Compatibility Path]
    L --> N[Dynamic Identity Path]
    L --> O[External Broker / Vault Path]

    M --> P[Broker Derives Short-Lived Access]
    N --> P
    O --> P

    P --> Q[Worker Receives Short-Lived Credential]
    Q --> R[Worker Invokes Reader]

    R --> S[Reader Opens Repository Stream]
    S --> T[Repository Platform]

    T --> U[Object Content Stream Returned]
    U --> V[Worker Streams Content to DSXA]
    V --> W[DSXA Returns Verdict / Result]
    W --> X[Core Persists Result and Updates State]
```