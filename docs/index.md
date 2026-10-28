#
<div style="display:flex; justify-content:center; margin-bottom:8px;">
  <img src="assets/dsx-header-logo.svg"
       alt="DSX-Connect"
       style="max-width:480px; width:100%; height:auto;" />
</div>

<p style="text-align:center; margin: 0 0 18px 0; font-size: 1.3em; font-weight: 600;">
  Protect and govern files across every repository.
</p>

<p style="text-align:center; max-width: 820px; margin: 0 auto 24px auto;">
  DSX-Connect provides repository protection and a File Gateway for
  <strong>Deep Instinct’s <a href="https://www.deepinstinct.com/dsx/dsx-applications">DSX for Applications</a></strong>.
  It connects cloud, SaaS, on-premises, and application-owned repositories to consistent scanning, policy, and remediation workflows.
</p>

<p style="text-align:center; max-width: 820px; margin: 0 auto 28px auto;">
  Use it to monitor new and changed files, run full repository scans, or let applications upload through the File Gateway.
</p>

![DSX-Connect connects repositories and applications to enterprise-controlled scanning, policy, and file handling](assets/diagrams/homepage-concept.svg#only-light)
![DSX-Connect connects repositories and applications to enterprise-controlled scanning, policy, and file handling](assets/diagrams/homepage-concept-dark.svg#only-dark)
<hr style="margin: 32px 0 24px 0; border: none; border-top: 1px solid rgba(0,0,0,0.1);" />

## Three Ways To Use DSX-Connect

### 1. Monitoring

Continuously watch repositories for new and changed files, while using baseline or full scans to establish coverage. Connectors handle repository-specific events, enumeration, credentials, and state so protection can converge over time.

Start with [Repository Monitoring](core-concepts/repository-monitoring.md) and the [Connector and Asset Model](core-concepts/connectors-and-assets.md). For deployment settings, see the [v2 connector guides](dsx-connect-2/deployment/connectors/index.md).

### 2. Full Scans

Run on-demand, scheduled, event-driven, or full-repository scans across cloud storage, SaaS platforms, fileshares, and mounted filesystems. DSX-Connect dispatches work to DSXA and exposes durable job state, results, retries, and operational metrics.

Start with [Full Repository Scan](core-concepts/repository-full-scan.md) or deploy the v2 core using the [Getting Started guide](dsx-connect-2/deployment/kubernetes-quickstart.md).

### 3. File Gateway

Give applications one API to discover approved destinations and upload files through enterprise controls. DSX-Connect coordinates scanning, policy, and delivery while repository credentials stay with IT / DevOps and file-handling decisions stay with Security.

Read [Governed File Movement](core-concepts/governed-file-movement.md) and [Application Identity and Attribution](dsx-connect-2/concepts/application-identity-and-attribution.md).

## What DSX-Connect Provides

* A reusable, event-driven scanning core built for predictable scale
* Pluggable connectors for cloud storage, SaaS platforms, and filesystems
* Repository monitoring, on-demand scans, and full-scan workflows
* A File Gateway for application uploads and controlled repository delivery
* Fault-tolerant execution with durable queues and retry handling
* Portable deployment via Docker Compose or Kubernetes (Helm)
* Seamless integration with DSX for Applications’ deep-learning malware detection

Whether protecting an existing repository or enforcing policy in an application file flow, DSX-Connect applies consistent malware prevention and governance wherever data moves.


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

* Use [Deployment](dsx-connect-2/deployment/index.md) for the v2 core and connectors.
* See [DSX-Connect Core](dsx-connect-2/deployment/kubernetes.md) and [PostgreSQL and RabbitMQ](dsx-connect-2/deployment/postgres-rabbitmq.md) for runtime settings.

If you are operating at scale:

* Use **Operations** for performance tuning, logging, monitoring, and upgrades.
* Refer to [Worker Scaling](core-concepts/architecture.md#worker-scaling) for the v2 execution model.

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

* [V2 Quickstart](dsx-connect-2/deployment/kubernetes-quickstart.md)
* [Deployment Overview](dsx-connect-2/deployment/index.md)

### 🧠 Core Concepts

* [Architecture Overview](core-concepts/architecture.md)
* [Connector and Asset Model](core-concepts/connectors-and-assets.md)
* [Application Identity and Attribution](dsx-connect-2/concepts/application-identity-and-attribution.md)
* [File Gateway](core-concepts/governed-file-movement.md)

### ⚙️ Deployment

* [DSX-Connect Core](dsx-connect-2/deployment/kubernetes.md)
* [Connectors](dsx-connect-2/deployment/connectors/index.md)
* [PostgreSQL and RabbitMQ](dsx-connect-2/deployment/postgres-rabbitmq.md)

### 🔧 Operations

* [Performance Tuning](operations/performance-tuning-job-comparisons.md)
* [Quarantine and Remediation](operations/quarantine-and-remediation.md)
* [Failed Scans and Dead Letter Queues](operations/dead-letter-queues.md)
* [Syslog Forwarding](operations/syslog.md)

### 👩‍💻 Developer's Guide

* [Developer Overview](developer/index.md)
* [DSXA SDK](developer/dsxa-sdk.md)

### 📚 Reference

* [Core Runtime Settings](dsx-connect-2/deployment/kubernetes.md)
* [Connector Settings](dsx-connect-2/deployment/connectors/index.md)
* [Filters Reference](reference/filters.md)

### 📦 Releases

* [GitHub Releases](https://github.com/deep-instinct/dsx-connect/releases)
* [Docker Hub Images](https://hub.docker.com/repositories/dsxconnect)
* [GitHub Repository](https://github.com/deep-instinct/dsx-connect)
