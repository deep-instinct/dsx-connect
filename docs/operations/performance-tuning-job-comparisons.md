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

## Full Scan Operational Model

Full scans establish baseline coverage across a repository at a point in operational time.

Because protected repositories remain active during scanning, full scans should be treated as best-effort enumeration of a live data set rather than immutable point-in-time snapshots.

Continuous monitoring or event-driven protection maintains convergence by detecting:

* newly created objects
* modified objects
* overwritten objects
* post-scan changes

Operationally:

* full scans are recommended during lower repository activity when possible
* monitoring should remain enabled for steady-state protection
* protection coverage is achieved through the combination of baseline scanning and continuous monitoring

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

## DSX-Connect NG Local Batch Defaults

For large local `dsx_connect_ng` batch scans, use deferred publish by default.

Deferred publish means the API persists the parent job, job items, and outbox rows first.
The relay then publishes scan messages gradually, honoring the active scan-item cap.
This prevents a large batch submit from flooding RabbitMQ and keeps API operations such as Swagger, progress polling, and cancel responsive.

Recommended local stack for 10k-item validation:

```bash
dsx-connect-ng-local \
  --with-postgres-docker \
  --with-rabbit-docker \
  --scan-worker-prefetch-count 100 \
  --policy-worker-prefetch-count 100 \
  --result-sink-worker-prefetch-count 100 \
  --relay-max-active-scan-items 100 \
  --no-stream-logs \
  foreground
```

Equivalent source checkout invocation:

```bash
./.venv/bin/python dsx_connect_ng/dsx_connect_ng/local/dsx_connect_ng_local.py \
  --with-postgres-docker \
  --with-rabbit-docker \
  --scan-worker-prefetch-count 100 \
  --policy-worker-prefetch-count 100 \
  --result-sink-worker-prefetch-count 100 \
  --relay-max-active-scan-items 100 \
  --no-stream-logs \
  foreground
```

Recommended validation command:

```bash
./.venv/bin/python scripts/validate_ng_batch_proxy_reader.py \
  --scan-only \
  --sample-kind benign \
  --item-count 10000 \
  --submit-timeout-seconds 600 \
  --poll \
  --poll-mode progress \
  --poll-timeout-seconds 3600 \
  --poll-interval-seconds 10
```

`validate_ng_batch_proxy_reader.py` now enables deferred publish by default.
Use `--no-defer-publish` only for small diagnostic runs where inline publish behavior is the thing being tested.

Completion semantics:

- Scan/result telemetry relay is auxiliary. DSXA reports authoritative malicious scan outcomes to DSX Console; DSX Connect may still relay scan results, DIANNA results, and scan stats to Vector, SIEMs, or other configured sinks.
- A batch should not remain non-terminal just because auxiliary scan-result telemetry is still being emitted or retried.
- Required durable work still gates workflow completion: scan completion, policy decisions needed for remediation, and remediation actions when configured.

Operational knobs:

| Setting | Recommended local value | Purpose |
| --- | ---: | --- |
| `--relay-max-active-scan-items` | `100` | Caps queued/scanning/scanned scan items so cancellation drains the latest active batch instead of a huge Rabbit backlog. |
| `--scan-worker-prefetch-count` | `100` | Allows the scan worker to keep enough work in flight to exercise reader/DSXA throughput. |
| `--policy-worker-prefetch-count` | `100` | Lets policy evaluation keep pace with the active scan slice instead of serializing `scanned -> deliver/completed` transitions. |
| `--result-sink-worker-prefetch-count` | `100` | Lets result emission keep pace when scan, remediation, DIANNA, or workflow-summary results are enabled. |
| `--no-stream-logs` | enabled | Writes logs to files without pushing high-volume worker logs through the terminal. |
| `--poll-mode progress` | enabled for large jobs | Polls aggregate progress instead of fetching thousands of job-item records repeatedly. |
| `--submit-timeout-seconds` | `600` for 10k | Allows initial persistence of large batches without treating local DB pressure as a client timeout. |

For Colima-backed Docker on a development machine, verify the VM allocation rather than host RAM:

```bash
colima list
```

For 10k-item local testing, `6GiB` is workable but tight for Postgres plus RabbitMQ under load.
Prefer around `10-12GiB` if the host has enough headroom:

```bash
colima stop
colima start --cpu 4 --memory 10 --disk 80
```

or:

```bash
colima start --cpu 6 --memory 12 --disk 80
```

Restart the local DSX-Connect NG stack after changing Colima resources.

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
