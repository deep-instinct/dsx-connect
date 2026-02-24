# Resource Recommendations

This chart deploys multiple components with very different resource profiles. Start with **requests** that reflect *typical* load, and use **limits** to cap runaway usage (or omit CPU limits if your cluster policy allows and you prefer bursty performance).

## What affects sizing

Your resource needs scale mostly with:

* **Scan throughput** (files/min), average file size, and concurrency
* **Connector behavior** (S3/GCS listing depth, retries, backpressure)
* **Retention + logging** (DB writes, syslog volume)
* **Result fanout** (SSE/WebSocket relay patterns, number of UI clients)

---

## Baseline tiers

### Tier 1: Local / dev (single user, light scans)

Use this for Colima/Minikube/k3s demos.

| Component                        | CPU Request | CPU Limit | Mem Request | Mem Limit |
| -------------------------------- | ----------: | --------: | ----------: | --------: |
| API (FastAPI)                    |        100m |      500m |       256Mi |     512Mi |
| Worker (Celery) *per replica*    |        200m |         1 |       512Mi |       1Gi |
| Redis                            |         50m |      250m |       256Mi |     512Mi |
| rsyslog                          |         25m |      100m |        64Mi |     128Mi |
| Optional in-cluster DSXA scanner |        500m |         2 |         1Gi |       4Gi |

Notes:

* This tier assumes **1–2 workers** and low concurrency.
* If you see OOMKills in workers, bump worker memory first.

---

### Tier 2: Shared cluster / staging (moderate scans, a few users)

Good for validating performance and autoscaling behavior.

| Component                        | CPU Request | CPU Limit | Mem Request | Mem Limit |
| -------------------------------- | ----------: | --------: | ----------: | --------: |
| API (FastAPI)                    |        250m |         1 |       512Mi |       1Gi |
| Worker (Celery) *per replica*    |        500m |         2 |         1Gi |       2Gi |
| Redis                            |        100m |      500m |       512Mi |       1Gi |
| rsyslog                          |         50m |      200m |       128Mi |     256Mi |
| Optional in-cluster DSXA scanner |           1 |         4 |         2Gi |       8Gi |

Notes:

* Typical starting point: **2–4 worker replicas**.
* If the API is mostly I/O bound, CPU is less important than keeping memory stable.

---

### Tier 3: Production (high throughput, sustained concurrency)

Use when you’re pushing high scan volume and want headroom.

| Component                        | CPU Request | CPU Limit | Mem Request | Mem Limit |
| -------------------------------- | ----------: | --------: | ----------: | --------: |
| API (FastAPI)                    |        500m |         2 |         1Gi |       2Gi |
| Worker (Celery) *per replica*    |           1 |         4 |         2Gi |       4Gi |
| Redis                            |        500m |         2 |         2Gi |       4Gi |
| rsyslog                          |        100m |      500m |       256Mi |     512Mi |
| Optional in-cluster DSXA scanner |           2 |         8 |         4Gi |      16Gi |

Notes:

* Expect to tune worker count + concurrency more than anything else.
* Redis memory should scale with queue depth (backlogs, retries, bursts).

---

## Helm values example

Paste and adjust (names may differ slightly depending on your chart’s keys):

```yaml
api:
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: "1"
      memory: 1Gi

worker:
  replicaCount: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "2"
      memory: 2Gi

redis:
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi

rsyslog:
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

dsxa:
  enabled: false
  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "4"
      memory: 8Gi
```

---

## Practical tuning guidance

* **Workers OOMkilled** → increase *worker memory request/limit* first, then reduce Celery concurrency if needed.
* **Backlog grows in Redis** → increase *worker replicas* and/or worker CPU, and ensure Redis has enough memory.
* **API latency spikes** → bump API memory to avoid GC churn, then add CPU if you’re truly CPU-bound.
* **rsyslog** is usually tiny unless you’re shipping very high log volume.

---

## Optional: autoscaling hints (if you enable HPA)

* **API**: scale on CPU (and optionally memory) if you expect many concurrent UI/SSE clients.
* **Workers**: scale on CPU is okay, but queue-depth-based scaling is better (if you later add a metric for Redis queue length).

---

If you tell me the exact values keys in your chart (`api.resources` vs `server.resources`, `workers` vs `celery`, etc.), I can rewrite the YAML snippet to match your chart 1:1.
