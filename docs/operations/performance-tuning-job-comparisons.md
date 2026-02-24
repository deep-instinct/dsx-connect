# Performance Tuning with Job Comparisons

This guide explains how to measure and tune DSX-Connect and DSXA performance using the Job Comparison feature.

This is a procedural workflow.

For:

* Performance theory → see [Concepts → Performance & Throughput](../concepts/performance.md)
* Metric definitions → see [Concepts → Job Comparison Explained](../concepts/job-comparison.md)
* Infrastructure scaling mechanics → see [Scaling & Performance (Kubernetes)](../deployment/kubernetes/scaling.md)

## Goal of Performance Tuning

The goal is not maximum concurrency.

The goal is sustained, predictable throughput without saturating:

* Connector sources
* Network bandwidth
* DSXA capacity
* CPU or memory
* Operational budget

---

## Step 1 — Establish a Baseline

1. Deploy with default settings.
2. Run a full scan on a representative dataset.
3. Record:

    * Job time
    * Total bytes/sec
    * Scan bytes/sec
    * Avg Req ms
    * CPU and memory utilization
    * DSXA utilization

This baseline becomes your reference point.

Do not tune without one.

---

## Step 2 — Increase Scan Request Worker Concurrency

Concurrency is the primary throughput lever.

Increase modestly:

2 → 4 → 6

Helm example:

```bash
helm upgrade --install dsx -n dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --set dsx-connect-scan-request-worker.celery.concurrency=4
```

Or in values.yaml:

```yaml
dsx-connect-scan-request-worker:
  celery:
    concurrency: 4
```

After each change:

* Re-run the same workload.
* Compare using Job Comparison.
* Observe CPU, memory, and DSXA saturation.

---

## Step 3 — Evaluate Throughput Gains

If:

* Total bytes/sec increases
* CPU and memory remain stable
* DSXA is not saturated

You may increase concurrency again.

Stop increasing concurrency when:

* Gains flatten
* CPU or memory saturate
* Network bandwidth peaks
* DSXA becomes the bottleneck
* Error rates increase

---

## Step 4 — Increase Replica Count

If per-pod resource limits are reached but cluster capacity remains:

Increase worker replicas.

Example:

```yaml
dsx-connect-scan-request-worker:
  replicaCount: 3
```

Replicas distribute workload across pods and nodes.

Re-test after each increase.

---

## Step 5 — Evaluate DSXA Capacity

If Scan Bytes/sec plateaus while Total Bytes/sec drops:

DSXA may be saturated.

Options:

* Increase DSXA resources
* Increase DSXA pod count (if in-cluster)
* Evaluate scan time per byte
* Review DSXA CPU utilization

Increasing DSX-Connect workers without DSXA capacity will only increase queue depth.

---

## Step 6 — Evaluate Connector and Network Limits

If workers appear idle:

* Connector enumeration may be slow.
* Asset may be too broad.
* Cloud API rate limits may be triggered.
* Network throughput may be saturated.

Consider:

* Asset-based sharding
* Multiple connector instances
* Narrower asset boundaries

---

## Step 7 — Use Job Comparison to Validate

After each change:

1. Re-run the same scan.
2. Compare jobs side-by-side.
3. Evaluate:

    * Lower total duration
    * Higher Total bytes/sec
    * Stable Scan bytes/sec
    * Acceptable Avg Req ms
    * Stable error rates

Change only one variable at a time.

---

## Capacity Planning with Projections

Use:

* Estimated Job Time: 1GB / 1TB
* Estimated DSXA Time projections

To answer:

* Can this configuration handle my dataset?
* Is this SLA realistic?
* Does increasing concurrency materially reduce projected time?

Always validate projections with representative workloads.

---

## Cost-Aware Decisions

Performance tuning is also cost tuning.

Example:

* Configuration A: 5 hours
* Configuration B: 4.5 hours
* Configuration B uses 40% more CPU

The correct configuration is the one that:

* Meets SLA
* Remains stable
* Minimizes cost

Fastest is not always best.

---

## When to Stop Tuning

Stop when:

* Throughput gains flatten
* Infrastructure approaches safe utilization
* DSXA is fully utilized
* Stability declines
* Cost outweighs benefit

Performance tuning is an optimization process — not a race.

