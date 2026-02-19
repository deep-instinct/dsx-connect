# Resource Recommendations (Kubernetes)

These are starting points for DSX-Connect and connectors. They assume streaming scans (no full file buffering), one file per scan request worker at a time, and typical office/PDF workloads. Use them as minimums and scale based on throughput goals.

## Core Components (per pod)

| Component | CPU (vCPU) | Memory | Notes |
| --- | --- | --- | --- |
| dsx-connect API | 0.25–0.5 | 256–512 MB | REST + UI + SSE. Mostly control-plane traffic. |
| scan_request worker | 0.5–1 | 512 MB–1 GB | Primary throughput lever. IO-bound + DSXA calls. |
| verdict_action worker | 0.25 | 256–512 MB | Connector callbacks for item actions. |
| results worker | 0.25 | 256–512 MB | Persists results, stats, syslog. |
| notification worker | 0.1–0.25 | 128–256 MB | SSE/pub-sub fanout. |
| Redis | 0.5–1 | 512 MB–2 GB | Queue depth + results retention drive memory. |
| rsyslog (optional) | 0.1–0.25 | 128–256 MB | Log collector only. |

## Connector Components (per pod)

| Connector Type | CPU (vCPU) | Memory | Notes |
| --- | --- | --- | --- |
| Filesystem | 0.25–0.5 | 256–512 MB | Local IO‑bound. |
| AWS S3 / Azure Blob / GCS | 0.5–1 | 512 MB–1 GB | Network/IO‑bound; scale replicas. |
| SharePoint / OneDrive / M365 / Salesforce | 0.5–1 | 512 MB–1 GB | API latency + rate limits dominate. |

## File Mix Examples (impact on throughput)

| Mix | Typical Size | What Changes |
| --- | --- | --- |
| Office/PDF only | Small–medium | High scan rate, connector IO is often the bottleneck. |
| Executables | Medium–large | DSXA scan time increases, CPU/network sensitivity grows. |
| Archives | Small–very large | DSXA scan time can dominate; scan_request can bottleneck per large archive; nested files increase total work. |

## Test and Tune (recommended process)

Use **Job Comparisons** in the UI to measure throughput on real workloads. Run representative jobs (same mix and size as production) and compare.

Then tune in this order:

1. **scan_request worker concurrency/replicas** (largest impact).
2. **Connector replicas** for IO‑heavy sources.
3. **Redis memory** (avoid evictions and backlog stalls).
4. **DSXA capacity** (scan time dominates for executables/archives).
5. **Network bandwidth/latency** between connector, core, and DSXA.

For Kubernetes, scale replicas or set per-worker concurrency in Helm values.

See Deployment Guides on the core and connectors for specific tuning information. 