# Performance & Throughput

This page explains what determines scan performance in DSX-Connect.

It describes the system model and common bottlenecks.
For step-by-step tuning guidance, see [Operations → Performance Tuning](../operations/performance-tuning-job-comparisons.md).
For infrastructure scaling mechanics, see [Kubernetes → Scaling & Performance](../deployment/kubernetes/scaling.md).

## The Scan Pipeline

Every file scanned by DSX-Connect follows the same pipeline:

1. The connector enumerates the file.
2. A Scan Request is created.
3. A Scan Request Worker retrieves the file (`read_file`).
4. The file is streamed to DSXA.
5. The DSXA verdict is returned.
6. If necessary, remediation is applied.
7. Results are persisted and broadcast.

This pipeline has multiple potential bottlenecks. Performance depends on how these stages interact.

## What Determines Throughput

Throughput is influenced by five major factors:

### 1. Connector Enumeration

Enumeration is typically the most serial phase of a full scan.

* Listing operations are often single-threaded at the provider level.
* Large assets (millions or billions of objects) can become enumeration-bound.
* Filters do not reduce enumeration cost — they only reduce scan requests created.

Using narrower **assets** reduces listing overhead.
Sharding assets enables parallel enumeration.

### 2. Worker Concurrency

Scan Request Worker concurrency determines how many files are processed simultaneously.

Increasing concurrency improves throughput until one of the following becomes saturated:

* CPU
* Memory
* Network bandwidth
* DSXA capacity

Concurrency increases parallelism, but also increases:

* Resource usage
* Context switching
* Network pressure
* Queue activity

There is always a point of diminishing returns.

---

### 3. Worker Replicas

Adding replicas increases horizontal capacity.

Conceptually:

* Concurrency increases parallelism inside a worker.
* Replicas increase parallelism across workers.

Replicas become important when:

* Per-pod resource limits are reached.
* You need distribution across nodes.
* You want operational isolation.

---

### 4. DSXA Scan Capacity

DSXA performs the actual file analysis.

For small office files, I/O and network often dominate.

For:

* Large executables
* Archives
* Deeply nested content

DSXA scan time may become the bottleneck.

If DSXA is saturated, increasing concurrency or replicas will only increase queue depth — not throughput.

---

### 5. Network and Infrastructure Limits

Throughput can also be constrained by:

* Network bandwidth between connectors and DSX-Connect
* Network bandwidth between DSX-Connect and DSXA
* Storage IOPS (filesystem connectors)
* Cloud API rate limits (S3, SharePoint, etc.)

Performance tuning must account for these environmental ceilings.

---

## Concurrency vs Replicas (Conceptual Model)

Both increase parallel processing, but they behave differently.

| Mechanism   | Effect                                      |
| ----------- | ------------------------------------------- |
| Concurrency | More parallel tasks within a worker         |
| Replicas    | More worker instances operating in parallel |

Tuning typically follows this conceptual pattern:

1. Increase concurrency while resources allow.
2. When gains flatten or instability appears, increase replicas.
3. If scan time dominates, evaluate DSXA scaling.

See [Operations → Performance Tuning](../operations/performance-tuning-job-comparisons.md) for the procedural workflow.

## Enumeration Ceilings and Asset Design

Enumeration is often the hidden bottleneck in large repositories.

If a connector must list billions of objects under one asset:

* Enumeration time dominates.
* Filtering does not reduce listing time.
* Workers may sit idle waiting for new scan requests.

The correct strategy is:

* Narrow asset boundaries.
* Use asset-based sharding.
* Deploy multiple connector instances for parallel enumeration.

Connector design directly affects throughput potential.

See [Connector Model](connectors.md) and [Scaling & Performance (Kubernetes)](../deployment/kubernetes/scaling.md) for more information.

## Throughput vs Latency

Higher concurrency increases total throughput but may increase:

* Per-file latency
* Resource pressure
* Queue contention

The goal is not maximum concurrency.

The goal is sustained, predictable throughput without saturating infrastructure.

## Cost vs Performance

In cloud environments, increasing concurrency and replicas increases:

* CPU allocation
* Memory allocation
* Network usage
* Operational cost

The optimal configuration is not always the fastest.

It is the configuration that meets:

* Throughput requirements
* SLA targets
* Budget constraints
* Operational stability goals

## Performance Is Systemic

Performance is not determined by DSX-Connect alone.

It is the interaction between:

* Connector enumeration
* Worker parallelism
* DSXA capacity
* Network bandwidth
* Infrastructure limits

Understanding this model is essential before making scaling decisions.

## See Also

* [Connector Model](connectors.md)
* [Job Comparison Explained](job-comparison.md)
* [Operations → Performance Tuning](../operations/performance-tuning-job-comparisons.md)
* [Scaling & Performance (Kubernetes)](../deployment/kubernetes/scaling.md)
