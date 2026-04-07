# DSX for Applications for SAP BTP

## Inline Upload Scanning with CAP

This document defines an inline scanning pattern for **SAP Business Technology Platform (BTP)** using a **CAP-based upload service** that calls **DSX for Applications (DSXA)** directly before storing uploaded files. The goal is to enforce **scan-before-store** for user-uploaded content such as resumes.

## Goals

* Enforce scan-before-store for uploaded files
* Keep storage and workflow ownership inside BTP
* Use CAP as the upload-handling service layer
* Call DSXA inline for malware scanning
* Support clean, malicious, and unscannable outcomes

## Core principle

> **BTP always owns file storage and workflow. DSXA provides the scan verdict.**

```text
User -> SAP Application -> CAP Upload Handler -> DSXA -> CAP decides -> BTP stores
```

## High-level flow

```mermaid
flowchart TD

    A["User<br/>(Uploads Resume)"]
    B["SAP Application"]
    C["Upload Handler / CAP Service"]
    D["DSXA Inline Scan"]
    E["CAP Decision Logic"]
    F["Store Clean File"]
    G["Quarantine File"]
    H["Put File on Hold"]

    A --> B
    B --> C
    C -->|scan before store| D
    D --> E
    E -->|clean| F
    E -->|malicious| G
    E -->|unscannable| H
```

## Detailed implementation flow

```mermaid
flowchart TD

    A["End User<br/>(Uploads Resume)"]

    subgraph BTP["SAP BTP Application Layer"]
        B["SAP Application UI / Service"]
        C["Upload Handler<br/>(CAP Service Endpoint)"]
        D["File Validation<br/>(size, type, required metadata)"]
        E["Inline Scan Request Builder<br/>(stream file + metadata to DSXA)"]
        I["Decision Logic in CAP<br/>(interpret DSXA result)"]
        J["User Response / Workflow Handling"]
        F["Primary Storage<br/>(clean files only)"]
        G["Quarantine Storage<br/>(malicious files)"]
        H["Hold / Pending Storage<br/>(unscannable or error)"]
    end

    subgraph DSXA["DSX for Applications"]
        X["DSXA Scan API"]
        Y["Malware Detection Engine"]
        Z["Scan Verdict Returned"]
    end

    A --> B
    B --> C
    C --> D
    D -->|valid upload| E
    D -->|invalid upload| J

    E -->|inline scan before storage| X
    X --> Y
    Y --> Z

    Z --> I

    I -->|clean| F
    I -->|malicious| G
    I -->|unscannable / timeout / scan error| H

    F --> J
    G --> J
    H --> J

    classDef user fill:#455a64,stroke:#263238,color:#ffffff
    classDef btp fill:#1565c0,stroke:#0d47a1,color:#ffffff
    classDef dsxa fill:#2e7d32,stroke:#1b5e20,color:#ffffff
    classDef storage fill:#6a1b9a,stroke:#4a148c,color:#ffffff
    classDef quarantine fill:#c62828,stroke:#8e0000,color:#ffffff
    classDef hold fill:#ef6c00,stroke:#e65100,color:#ffffff

    class A user
    class B,C,D,E,I,J btp
    class X,Y,Z dsxa
    class F storage
    class G quarantine
    class H hold
```

## Implementation Patterns

There are three practical ways to integrate DSXA into a BTP application.

---

### Option 1 — Inline Scan in Existing Application (Preferred)

#### Description

Existing customer managed SAP application handles uploads and calls DSXA **directly before storing the file**.

This is the **cleanest and most direct implementation**.

---

#### Flow

```mermaid
flowchart TD

    A["User<br/>(Uploads Resume)"]
    B["SAP Application"]
    C["Upload Handler<br/>(Existing Backend Service)"]
    D["DSXA Inline Scan"]
    E["Application Decision Logic"]
    F["Primary Storage<br/>(clean files only)"]
    G["Quarantine Storage<br/>(malicious files)"]
    H["Hold / Pending<br/>(unscannable)"]

    A --> B
    B --> C
    C -->|scan before store| D
    D --> E

    E -->|clean| F
    E -->|malicious| G
    E -->|unscannable| H
```

---

#### Responsibilities

**Application**

* receives upload
* calls DSXA
* interprets result
* executes storage decision

**DSXA**

* scans file
* returns verdict

---

#### When to use

* application backend is accessible
* upload handler can be modified
* goal is fastest and simplest implementation

---

### Option 2 — CAP Sidecar / Upload Gateway

#### Description

A **CAP-based service** is introduced as an **upload proxy** that performs scanning before passing the file to the application or storage layer.

---

#### Flow

```mermaid
flowchart TD

    A["User<br/>(Uploads Resume)"]
    B["SAP Application"]
    C["CAP Upload Gateway"]
    D["DSXA Inline Scan"]
    E["CAP Decision Logic"]
    F["Primary Storage"]
    G["Quarantine"]
    H["Hold"]

    A --> B
    B --> C
    C -->|scan before store| D
    D --> E

    E -->|clean| F
    E -->|malicious| G
    E -->|unscannable| H
```

---

#### Responsibilities

**CAP Gateway**

* receives or proxies upload
* calls DSXA
* applies decision logic
* forwards or stores file

---

#### When to use

* existing app cannot be modified easily
* need a reusable scanning layer
* want separation of concerns

---

### Option 3 — Post-Upload Scanning (Fallback)

#### Description

The file is stored first, then scanned afterward.

---

#### Flow

```mermaid
flowchart TD

    A["User Upload"]
    B["Application"]
    C["Storage"]
    D["DSXA Scan (async)"]
    E["Remediation Action"]

    A --> B
    B --> C
    C --> D
    D --> E
```

---

#### ⚠️ Important

> This is **not scan-before-store**

---

#### When to use

* no ability to intercept uploads
* legacy constraints
* temporary fallback

---

## Decision Model

All patterns use the same outcome model:

| Verdict     | Action               |
| ----------- | -------------------- |
| Clean       | Store file           |
| Malicious   | Quarantine or reject |
| Unscannable | Hold for review      |

---

## Role of CAP

CAP is **one possible implementation mechanism**, not a requirement.

CAP can:

* act as upload handler (Option 1)
* act as sidecar/gateway (Option 2)

But the architecture does **not depend on CAP**.

---

## Future Implementation — DSX-Connect

As the system evolves, DSX-Connect can be introduced as a **centralized control plane**.

---

### Why introduce DSX-Connect

In Options 1 and 2, decision logic lives in application or CAP code:

* quarantine vs reject behavior
* hold logic
* file-type rules
* audit normalization

Over time, this becomes harder to maintain.

---

### Future flow

```text
User → Application → DSX-Connect → DSXA → DSX-Connect decision → Application executes
```

---

### What changes

**Instead of:**

* CAP/application interprets DSXA result

**You get:**

* DSX-Connect applies policy
* returns normalized action

---

### Benefits

* centralized policy
* less application code
* consistent decisions across systems
* reusable across platforms
* improved audit visibility

---

