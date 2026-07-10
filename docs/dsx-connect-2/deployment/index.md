# DSX-Connect 2 Deployment

DSX-Connect 2 deployment is split into two concerns:

1. Deploy the DSX-Connect 2 control plane.
2. Deploy one or more connectors that register with that control plane.

This split matters operationally.
The control plane owns durable state, job orchestration, worker queues, scan result handling, and the Operator Console.
Connectors own repository-specific access, discovery, reads, monitoring, and remediation actions.

## Recommended Documentation Split

Use these pages as the deployment path:

| Page | Purpose |
| --- | --- |
| [Kubernetes Helm](kubernetes.md) | Deploy the DSX-Connect 2 control plane from released Helm charts |
| [Connectors](connectors/index.md) | Deploy repository connectors for DSX-Connect 2 |
| [Development](development.md) | Build local images and use helper scripts for development deployments |

Future pages should stay focused:

| Future page | Purpose |
| --- | --- |
| Operations | Runtime checks, logs, teardown, upgrades, and troubleshooting |
| Scanner configuration | Stub, external DSXA, and containerized DSXA deployment |
| Protection profiles | Asset protection defaults, profile assignment, and bulk enablement |
| Production hardening | durable storage, secrets, ingress, TLS, auth, scaling, and resource limits |

## Local Kubernetes Assumptions

The current quick path assumes:

* Docker or Colima is running
* Kubernetes is available, such as k3s under Colima
* `kubectl` points at the intended cluster
* `helm` is installed
* released images are reachable from the cluster, or local images are loaded for development testing

For a remote cluster, use released images or push development images to a registry the cluster can pull from.

## Namespace

The examples use a shared namespace:

```bash
kubectl create namespace dsx-connect
```

The deployment scripts also pass `--create-namespace` to Helm, so creating the namespace manually is optional.
