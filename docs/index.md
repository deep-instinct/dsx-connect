#
<div style="display:flex; justify-content:center; margin-bottom:8px;">
  <img src="assets/dsx-header-logo.svg"
       alt="DSX-Connect"
       style="max-width:480px; width:100%; height:auto;" />
</div>

<p style="text-align:center; margin: 0 0 18px 0; font-size: 1.3em; font-weight: 600;">
  Any file. Anywhere.
</p>

<p style="text-align:center; max-width: 820px; margin: 0 auto 24px auto;">
  DSX-Connect is a modular, event-driven orchestration framework that extends 
  <strong>Deep Instinct’s <a href="https://www.deepinstinct.com/dsx/dsx-applications">DSX for Applications</a></strong> 
  to protect files across cloud, SaaS, and on-prem repositories.
</p>

<p style="text-align:center; max-width: 820px; margin: 0 auto 28px auto;">
  It standardizes how files are discovered, scanned, and remediated — enabling deep-learning malware prevention against zero-day and AI-generated threats wherever data resides.
</p>

<p style="text-align:center;">
  <img src="assets/dsx-connect-design.svg" alt="DSX-Connect Architecture" style="max-width: 100%; height: auto;" />
</p>
<hr style="margin: 32px 0 24px 0; border: none; border-top: 1px solid rgba(0,0,0,0.1);" />
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

* [Configuration Reference](deployment/kubernetes/configuration-reference.md)
* [Environment Variables](deployment/kubernetes/configuration-reference.md#global-settings)
* [Filters Reference](reference/filters.md)

### 📦 Releases

* [Docker Compose Bundles](https://github.com/deep-instinct/dsx-connect/releases)
* [Docker Hub Images](https://hub.docker.com/repositories/dsxconnect)
* [GitHub Repository](https://github.com/deep-instinct/dsx-connect)
