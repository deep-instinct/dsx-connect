# Integration Patterns Model

## Purpose

This document defines the primary integration patterns supported by DSX-Connect as a Security Hub.

Rather than organizing around features like "monitoring" or "scanning," DSX-Connect separates integrations based on **how and where file decisions are made**.

---

## Core Principle

DSX-Connect supports two primary integration patterns:

- Native Application Integrations
- Connector Integrations

Both patterns feed into the same **Security Hub (DSX-Connect core)**, which provides:

- scanning (via DSXA)
- policy evaluation
- decisioning
- audit and logging
- workflow (hold/manual review)
- job lifecycle management

---

## 1. Native Application Integrations

### Definition

Integrations where DSX-Connect is called **directly within an application workflow**, typically before a file is stored or processed.

---

### Key Characteristics

- synchronous / inline
- decision before persistence
- application enforces outcome
- no connector required

---

### Typical Flow

1. Application receives file
2. Application calls DSX-Connect (`/scan`)
3. DSX-Connect evaluates file + policy
4. DSX-Connect returns decision
5. Application enforces decision (store, reject, quarantine)

---

### Best For

- upload protection
- inline scanning
- real-time decisioning
- business-process-aware enforcement
- "scan before store"

---

### Examples

- CAP / BTP application
- Node.js or Java backend
- internal upload portal
- SaaS platform with plugin/app model

---

### Key Insight

> Native integrations answer:  
> “How do I protect files before they are stored or processed?”

---

## 2. Connector Integrations

### Definition

Integrations where DSX-Connect interacts with external platforms or repositories through APIs, filesystems, or event systems.

---

### Key Characteristics

- asynchronous or event-driven
- operates on existing or externally created content
- relies on platform APIs or storage systems
- supports monitoring, enumeration, and remediation

---

### Capabilities

- monitor for changes (events, webhooks, polling)
- enumerate existing content (batch + cursor)
- fetch content
- submit scan jobs
- perform remediation actions

---

### Typical Flow (Monitoring)

1. External platform emits event (or connector polls)
2. Connector detects new/changed object
3. Connector submits item to DSX-Connect
4. DSX-Connect scans + evaluates policy
5. DSX-Connect triggers remediation if needed

---

### Typical Flow (Bulk)

1. DSX-Connect requests enumeration
2. Connector returns batch + cursor
3. DSX-Connect accepts items and creates jobs
4. Workers process items asynchronously

---

### Best For

- large-scale repository scanning
- existing content protection
- event-driven scanning
- monitoring external systems
- bulk and async workloads

---

### Examples

- AWS S3
- Google Cloud Storage
- SharePoint / OneDrive
- filesystem (local, NFS, SMB)
- SaaS repositories (Salesforce, etc.)

---

### Key Insight

> Connector integrations answer:  
> “How do I protect files that already exist in, or arrive through, external systems?”

---

## 3. Shared Security Hub (DSX-Connect Core)

Both integration patterns rely on the same core services:

- DSXA scanning engine integration
- policy evaluation
- verdict normalization
- decision model (allow, block, quarantine, hold)
- audit and logging
- job lifecycle management
- workflow orchestration

This ensures:

- consistent decisions across all sources
- unified reporting
- centralized control plane

---

## Why This Model Exists

This separation avoids:

- overloading connectors with inline responsibilities
- forcing applications to use connectors unnecessarily
- mixing real-time and batch concerns
- inconsistent policy enforcement

It enables:

- clean developer experience (FSaaS)
- scalable repository protection
- unified architecture

---

## Relationship to Other Models

This model works alongside:

- protected scope model → defines ownership boundaries
- connector contract model → defines connector responsibilities
- job lifecycle model → defines async processing
- inline scan service model → defines native app usage

---

## Current Direction

DSX-Connect should:

- prioritize native integrations for inline use cases
- use connectors for repository/platform use cases
- maintain a single shared decision plane across both