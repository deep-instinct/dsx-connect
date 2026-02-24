# 
<p style="text-align:center; margin: 0 0 4px 0;">
  <img src="assets/dsx-header-logo.svg" alt="DSX-Connect" width="640" height="120" style="display:inline-block; vertical-align:middle;" />
</p>
<p style="text-align:left; margin: 0 0 12px 0;"><strong>Stop zero-day and AI-generated malware - any file, anywhere.</strong></p>

DSX-Connect is a modular, event-driven framework that extends **Deep Instinct's** [**DSX for Applications**](https://www.deepinstinct.com/dsx/dsx-applications) (DSXA) to any repository or service.
It orchestrates how files are discovered, scanned, and remediated—allowing Deep Instinct’s deep-learning engine to protect cloud, SaaS, and on-prem data against even previously unseen threats.

Powered by Deep Instinct’s deep-learning engine, DSX-Connect detects and prevents malware without relying on signatures, heuristics, or sandboxing—making it effective against zero-day attacks and GenAI-generated malware.
![DSX‑Connect Architecture](assets/dsx-connect-design.svg)

At its core, DSX-Connect provides a reusable scanning engine built around queues and workers, while pluggable DSX-Connectors adapt that engine to each repository or service. This architecture separates what is scanned from where it lives, making it easy to scale protection without re-architecting your environment.
What DSX-Connect gives you: 

- A reusable scanning core built on queues and workers for predictable, scalable processing
- Pluggable connectors for cloud storage, SaaS platforms, and filesystems
- Support for on-demand and on-access scanning workflows
- Event-driven, fault-tolerant execution designed for high-volume environments 
- Portable deployments via Docker Compose or Kubernetes / Helm 
- Seamless integration with DSX for Applications’ deep-learning malware detection and remediation

Whether you’re protecting cloud buckets, enterprise SaaS data, or on-prem filesystems, DSX-Connect lets you standardize how scanning happens—while keeping deployment flexible and operations observable.

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
