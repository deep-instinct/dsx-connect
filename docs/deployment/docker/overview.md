# Docker Compose Overview

Docker Compose provides a simple, single-host deployment model for DSX-Connect.

It is ideal for:

* Development and testing
* Proof-of-concept environments
* Small or controlled production workloads
* Isolated lab deployments

Docker Compose runs all services (API, workers, Redis, optional DSXA, connectors) on a single Docker host using static configuration and `.env` files.

---

## When to Use Docker Compose

Docker Compose is appropriate when:

* You are evaluating DSX-Connect
* You are developing or testing connectors
* You have a single-node deployment requirement
* You do not require autoscaling or high availability
* You want a lightweight operational footprint

Compose keeps the system simple and predictable.

---

## Scaling Characteristics

In Docker Compose, the primary throughput control is worker concurrency.

You may also manually scale containers using Compose commands, but scaling remains:

* Single-host
* Manually controlled
* Without autoscaling
* Without multi-node scheduling

Docker Compose does not provide:

* Horizontal Pod Autoscaling (HPA)
* Cluster-level resource scheduling
* Node distribution
* Native high-availability patterns
* Production-grade secret orchestration

For large-scale, multi-node, or autoscaled environments, use the Kubernetes (Helm) deployment.

See [Choosing Your Deployment](../../concepts/deployment-models.md) for a full comparison.

---

## Configuration Model

Docker Compose uses:

* Static YAML templates
* Environment variables supplied via `.env` files
* Optional override files for TLS or customization

Best practice:

* Keep the Compose YAML unchanged.
* Pin image versions in `.env` files.
* Maintain separate env files per environment (dev/stage/prod).

This model keeps deployments reproducible and easy to reason about.

---

## Secrets and Credentials

Connectors typically require credentials to access external repositories.

For local or short-lived environments, `.env` files are convenient.

For longer-running or shared environments:

* Use a secrets manager when possible.
* Avoid committing real secrets.
* Restrict file permissions.
* Rotate credentials regularly.

If strong secret management, role-based access control, or automated secret synchronization is required, Kubernetes is recommended.

---

## TLS Considerations

For local development:

* Mount certificates at runtime.

For production-grade certificate management, ingress integration, and certificate automation, use the Kubernetes deployment.

---

## Operational Boundaries

Docker Compose is intentionally simple.

It prioritizes:

* Predictability
* Ease of deployment
* Low operational overhead

It does not aim to provide:

* Elastic scaling
* Cluster scheduling
* Advanced workload isolation
* Enterprise orchestration patterns

When your environment requires those capabilities, transition to Kubernetes.

---

## Next Steps

* [Resource Recommendations](resource-recommendations.md)
* [Core Deployment (Docker Compose)](dsx-connect.md)
* Connector Deployment (Docker Compose)
