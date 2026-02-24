# Choosing Your Deployment: Docker Compose vs Kubernetes

DSX-Connect supports two deployment models:

* Docker Compose
* Kubernetes (Helm)

Both run the same core services and scanning workflow.
They differ in operational capabilities, scalability, and production readiness.

This page explains when to use each model.

## Architectural Equivalence

Both deployment models include:

* API service
* Scan request workers
* Verdict and results workers
* Redis
* Optional DSXA scanner
* Optional log collector

The difference is not functionality — it is **operational control and scalability**.

## Docker Compose

Docker Compose is intended for:

* Local development
* Functional validation
* Proof-of-concept deployments
* Single-host evaluation
* Short-lived or controlled scan jobs

### Characteristics

* Single host
* No horizontal orchestration across nodes
* Limited scaling (concurrency tuning only)
* No native autoscaling
* No resource requests/limits enforcement

Compose provides a lightweight, low-friction way to run the full platform.  It is intentionally minimal.

### Scaling in Compose

In Docker Compose, the primary throughput control is:

```
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY
```

You may also scale services manually using Docker Compose (for example, increasing the number of worker containers) and define basic CPU/memory limits in the Compose file.

However, Compose does not provide:

* Native autoscaling (e.g., Horizontal Pod Autoscaler)
* Multi-node scheduling or workload distribution
* Kubernetes-style resource requests/limits with cluster-level enforcement
* Built-in high-availability patterns (e.g., HA Redis)
* Operational scaling patterns such as asset-based connector sharding across managed replicas

For large-scale, multi-node, or production workloads requiring controlled horizontal scaling and resource governance, the Kubernetes (Helm) deployment is recommended.

## Kubernetes (Helm)

Kubernetes is the supported path for operational and production deployments.

It is recommended when you require:

* Horizontal scaling (replicas)
* Autoscaling (HPA)
* Resource requests and limits
* Multi-node deployments
* Connector sharding via `DSXCONNECTOR_ASSET`
* High-availability Redis
* Secret management
* Enrollment and HMAC enforcement
* Automated TLS and ingress
* Predictable scheduling and isolation
* GitOps workflows

### Scaling in Kubernetes

Kubernetes enables:

* Tuning `dsx-connect-scan-request-worker.celery.concurrency`
* Increasing replica count
* Horizontal Pod Autoscaling
* Dedicated node pools
* Asset-based connector sharding
* Independent DSXA scaling

This allows scaling both vertically and horizontally while maintaining operational stability.

## Capability Comparison

| Capability                 | Docker Compose | Kubernetes      |
| -------------------------- | -------------- | --------------- |
| Increase concurrency       | Yes            | Yes             |
| Increase replicas          | Limited/manual | Native          |
| Horizontal autoscaling     | No             | Yes             |
| Resource requests/limits   | No             | Yes             |
| Multi-node deployment      | No             | Yes             |
| Connector sharding pattern | Manual         | Supported model |
| High-availability Redis    | No             | Yes             |
| Secret management          | Limited        | Native          |
| Automated TLS              | Manual         | Native          |

## Performance and Throughput Implications

If you are:

* Increasing replica counts
* Sharding connectors across assets
* Scaling DSXA pods
* Managing CPU/memory budgets
* Enforcing authentication at scale
* Automating TLS lifecycle
* Planning sustained multi-terabyte scans

You are operating in Kubernetes territory.

Docker Compose remains ideal for:

* Development
* Functional validation
* Throughput experimentation
* Smaller, controlled scan workloads

## Recommended Path

A common lifecycle:

1. Develop and validate using Docker Compose.
2. Use Job Comparisons to understand performance characteristics.
3. Move to Kubernetes for production scaling and operational control.

The deployment model should match the operational maturity and scale of your environment.
