# 
<p style="text-align:center; margin: 0 0 4px 0;">
  <img src="assets/dsx-header-logo.svg" alt="DSX-Connect" width="640" height="120" style="display:inline-block; vertical-align:middle;" />
</p>
<p style="text-align:left; margin: 0 0 12px 0;"><strong>Stop zero-day and AI-generated malware in any repository, anywhere.</strong></p>

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



## Quick Links
- [Overview](overview.md)
- [Getting Started](getting-started.md)
- [Connectors](connectors/index.md)
- [Deployment Models](deployment/index.md)
- [Deployment Advanced Settings](deployment/advanced.md)
- [Filters Reference](reference/filters.md)
