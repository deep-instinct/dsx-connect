# Resource Recommendations (Docker)

These are starting points for DSX-Connect and connectors running under Docker Compose. 
They assume streaming scans from Connectors (no full file buffering), 
one file per scan request worker at a time, and typical file workloads.

## Overall Docker Host / Docker Host VM Sizing

Docker essentially takes on the resources of its host Linux system, whether baremetal or a Linux VM.   For Docker Desktop (Windows/macOS)
the same rule applies (under the covers, Docker Desktop is simply running Docker on a Linux VM on top of the host OS), so 
whatever resources are allocated to Docker Desktop's VM, are available to DSX-Connect containers.
Docker Compose does not enforce granular per‑container CPU/RAM limits in standard mode, so treat these as **overall Docker host** recommendations:

| Deployment Size | CPU | RAM | Notes                                                             |
|-----------------| --- | --- |-------------------------------------------------------------------|
| Dev/test/POV    | 4 vCPU | 8 GB | Enough for core + one connector + local DSXA scanner.             |
| Medium          | 8 vCPU | 16 GB | Supports multiple connectors and higher scan concurrency. |
| Large           | 16+ vCPU | 32+ GB | For higher scan volume or larger file mixes.                      |

If you need strict per‑container limits, use Kubernetes (k3s/k8s). We do not support Swarm‑specific tuning in this guide.

## File Mix Examples (impact on throughput)

| Mix | Typical Size | What Changes                                                                                                                                                                                                 |
| --- | --- |--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Office/PDF only | Small–medium | High scan rate, connector IO is often the bottleneck (i.e how fast can the connector read the file off the repository). Concurrent Scan Request Workers increase the number that can be processed at a time. |
| Executables | Medium–large | Connector <-> Scan Request Worker <-> DSXA Scanner time increases, moving file from repo to scanner.                                                                                                         |
| Archives | Small–very large | DSXA scan time increases; scan_request Worker IO-bound on large archives; nested files increase total work.                                                                                                  |

## Test and Tune (recommended process)

Use **Job Comparisons** in the UI to measure throughput on real workloads. Run representative jobs (same mix and size as production) and compare:

- Total bytes/sec and DSXA scan time per GB.
- Job wall time and queue wait time.

Then tune in this order:

1. **scan_request worker concurrency** (largest impact).
2. **Connector replicas** for IO‑heavy repositiry sources.
3. **Redis memory** (avoid evictions and backlog stalls).
4. **DSXA capacity** (scan time increases for larger files and archives).
5. **Network bandwidth/latency** between connector, core, and DSXA.   Ultimately the speed of processing a single file is dominated by this factor, but also typically the last thing that can be tuned.

For Docker Compose, concurrency can be configured on deployment (`sample.core.env` example shown):
```dotenv
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY=4
DSXCONNECT_VERDICT_ACTION_WORKER_CONCURRENCY=1
DSXCONNECT_RESULTS_WORKER_CONCURRENCY=1
DSXCONNECT_NOTIFICATION_WORKER_CONCURRENCY=1
```
