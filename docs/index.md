#
<p style="text-align:center; margin: 0 0 4px 0;"> <img src="assets/dsx-header-logo.svg" alt="DSX-Connect" width="640" height="120" style="display:inline-block; vertical-align:middle;" /> </p> <p style="text-align:left; margin: 0 0 12px 0; font-size: 1.1em;"> <strong>Any file. Anywhere.</strong> Stop zero-day and AI-generated malware.</p>

DSX-Connect is a modular, event-driven orchestration framework that extends Deep Instinct’s DSX for Applications
(DSXA) to protect files across cloud, SaaS, and on-prem repositories.

It standardizes how files are discovered, scanned, and remediated — allowing Deep Instinct’s deep-learning engine to prevent zero-day and AI-generated malware wherever data resides.

![DSX‑Connect Architecture](assets/dsx-connect-design.svg)

At its core, DSX-Connect separates where files live from how they are scanned.

A reusable scanning engine built on queues and workers handles orchestration, while pluggable connectors adapt that engine to each repository.

This architecture enables consistent protection across environments — without re-architecting your infrastructure.

What DSX-Connect Provides

* A reusable, event-driven scanning core built for predictable scale 
* Pluggable connectors for cloud storage, SaaS platforms, and filesystems 
* Support for on-demand and event-driven scanning workflows 
* Fault-tolerant execution with durable queues and retry handling 
* Portable deployment via Docker Compose or Kubernetes (Helm)
* Seamless integration with DSX for Applications’ deep-learning malware detection

Whether protecting cloud buckets, enterprise SaaS data, or on-prem filesystems, DSX-Connect enables consistent malware prevention — any file, anywhere.

## Who This Is For

This documentation is intended for:

- Security engineers deploying file scanning across repositories
- Platform engineers operating DSX-Connect at scale
- DevOps teams integrating DSX-Connect into CI/CD or cloud workflows
- Architects evaluating deployment models


## About the Documentation

The DSX-Connect documentation is organized by role and lifecycle stage.

If you are new to DSX-Connect:

* Start with **Getting Started** for a quick deployment.
* Review **Core Concepts** to understand architecture, connectors, and performance.

If you are deploying:

* Use **Deployment** for Docker Compose or Kubernetes (Helm).
* See **Choosing Your Deployment** to understand the trade-offs.

If you are operating at scale:

* Use **Operations** for performance tuning, logging, monitoring, and upgrades.
* Refer to **Scaling & Performance (Kubernetes)** for infrastructure-level scaling.

If you need configuration details:

* Use **Reference** for environment variables, Helm values, and API definitions.

This structure separates:

* System concepts
* Deployment mechanics
* Operational procedures
* Reference material

So you can quickly find what you need.

---

## Quick Links

### 🚀 Getting Started

* [Overview](getting-started/overview.md)
* [Docker Compose Quickstart](getting-started/docker-quickstart.md)
* [Kubernetes (Helm) Quickstart](getting-started/kubernetes-quickstart.md)

### 🧠 Core Concepts

* [Architecture Overview](concepts/architecture.md)
* [Connector Model](concepts/connectors.md)
* [Performance & Throughput](concepts/performance.md)
* [Choosing Your Deployment](concepts/deployment-models.md)

### ⚙️ Deployment

* [Docker Compose Overview](deployment/docker/overview.md)
* [Kubernetes (Helm) Deployment](deployment/kubernetes/dsx-connect.md)
* [Scaling & Performance (Kubernetes)](deployment/kubernetes/scaling.md)

### 🔧 Operations

* [Performance Tuning](operations/performance-tuning-job-comparisons.md)
* [Syslog Forwarding](operations/syslog.md)

### 📚 Reference

* [Configuration Reference](reference/configuration.md)
* [Environment Variables](reference/environment.md)
* [Filters Reference](reference/filters.md)

### 📦 Releases

* [Docker Compose Bundles](https://github.com/deep-instinct/dsx-connect/releases)
* [Docker Hub Images](https://hub.docker.com/repositories/dsxconnect)
* [GitHub Repository](https://github.com/deep-instinct/dsx-connect)
