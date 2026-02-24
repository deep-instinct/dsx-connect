# Resource Recommendations (Docker)

These are starting points for DSX-Connect and connectors running under Docker Compose.

They assume:

* One file processed per scan request worker at a time
* Typical business file workloads
* A single-host Docker environment

These recommendations apply to the overall Docker host (or Docker Desktop VM).

## Docker Host Sizing

Docker containers consume resources from the underlying Linux host (or Docker Desktop VM on macOS/Windows).

Ensure Docker Desktop is allocated sufficient CPU and memory for the expected workload.

| Deployment Size  | CPU      | RAM    | Notes                                        |
| ---------------- | -------- | ------ | -------------------------------------------- |
| Dev / Test / POC | 4 vCPU   | 8 GB   | Core + one connector + optional local DSXA   |
| Medium           | 8 vCPU   | 16 GB  | Multiple connectors and moderate concurrency |
| Large            | 16+ vCPU | 32+ GB | Higher scan volume or larger file workloads  |

These are host-level sizing guidelines.

While Docker supports per-container limits, Compose deployments typically rely on overall host sizing rather than cluster-level resource scheduling. For strict workload isolation or node-level resource governance, use Kubernetes.

---

## Workload Considerations

Resource requirements vary depending on:

* File size distribution
* File type mix
* DSXA scan cost per byte
* Connector I/O performance
* Network throughput between connector, core, and DSXA

In many environments:

* Small office documents are I/O-bound.
* Large binaries and archives increase DSXA processing time.
* Deeply nested archives increase total scan work.

Because Docker runs all services on a single host, CPU, memory, disk I/O, and network bandwidth are shared across:

* API
* Workers
* Redis
* Connectors
* Optional DSXA container

Monitor system-level utilization to avoid contention.

## Concurrency in Docker

Throughput in Docker Compose is primarily controlled via worker concurrency, and of these scan_request workers affect throughput the most.

Example:

```dotenv
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY=4
DSXCONNECT_VERDICT_ACTION_WORKER_CONCURRENCY=1
DSXCONNECT_RESULTS_WORKER_CONCURRENCY=1
DSXCONNECT_NOTIFICATION_WORKER_CONCURRENCY=1
```

For structured tuning guidance, see:

[Operations → Performance Tuning](../../operations/performance-tuning-job-comparisons.md)
