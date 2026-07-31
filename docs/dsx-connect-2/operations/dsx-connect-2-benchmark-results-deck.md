# DSX-Connect 2 Benchmark Results

## Slide 1 - Title

**DSX-Connect 2 Benchmark Results**

Faster connector protection while preserving the core architectural model:

```text
Connector owns repository access
DSX-Connect owns durable workflow, policy, and operational visibility
DSXA owns scan verdicts
```

---

## Slide 2 - Executive Summary

DSX-Connect 2 is showing material throughput gains over the DSX-Connect 1G benchmark baseline.

The important part is not only that 2G is faster.

It is faster while maintaining real persisted workflow state:

- jobs
- items
- scan stages
- policy stages
- remediation state
- result metadata
- cancellation state
- operator-visible scan statistics

---

## Slide 3 - Headline Benchmark

Comparable GCS batch shape:

| System | Corpus | Runtime | Throughput |
| --- | ---: | ---: | ---: |
| DSX-Connect 1G GCS batch reference | `1002` files | `159s` | `6.3 files/s` |
| DSX-Connect 2 k3s GCS proxy run | `4468` files | `146.206s` | `30.560 files/s` |

That is roughly:

```text
30.560 / 6.3 = 4.85x
```

---

## Slide 4 - Why This Result Matters

The 2G result is not an in-memory shortcut.

The measured 2G runs used:

- PostgreSQL for durable state
- RabbitMQ for worker dispatch
- persisted batch jobs
- persisted item records
- persisted terminal outcomes
- policy progression
- scan statistics
- operator-visible progress

This is a stronger result than raw throughput alone.

---

## Slide 5 - Persistence Is The Product

DSX-Connect 2 is preserving the operational contract:

| Persistent Record | Why It Matters |
| --- | --- |
| Job | Operators can see what was requested and where it stands. |
| Item | Every accepted file has durable membership in the job. |
| Scan result | DSXA results can be inspected and compared. |
| Policy state | Protection behavior is explainable after scan. |
| Remediation state | Actions can be audited or retried. |
| Cancellation state | Operator intent is recorded and propagated. |

The system is faster while becoming more observable and recoverable.

---

## Slide 6 - What Changed Versus 1G

The biggest improvement is batch-oriented scanning.

1G behavior was more exposed to one-file-at-a-time overhead.

2G improves the shape of the workload:

```text
persist accepted batch
publish work in bounded batches
scan with worker concurrency
complete outcomes in bulk
derive progress from durable item state
```

Batch scanning made the architecture faster without making DSX-Connect repository-specific.

---

## Slide 7 - Worker Scaling Evidence

k3s GCS proxy-reader runs:

| Scan Workers | Items | Runtime | Throughput |
| ---: | ---: | ---: | ---: |
| `1` | `4468` | `251.927s` | `17.735 files/s` |
| `2` | `4468` | `177.632s` | `25.153 files/s` |
| `4` | `4468` | `146.206s` | `30.560 files/s` |

The worker model scales throughput, but scanner/API latency rises as concurrency increases.

That gives operators tuning data instead of guesswork.

---

## Slide 8 - Native Readers Were Not The Win

Native repository readers were a concern because they weaken the repo-agnostic model.

The benchmark results did not show a decisive native-reader advantage.

| Environment | Reader | Items | Throughput |
| --- | --- | ---: | ---: |
| k3s lab | proxy | `4468` | `30.560 files/s` |
| k3s lab | native | `4468` | `31.448 files/s` |
| GKE lab | proxy | `500` | `15.281 files/s` |
| GKE lab | native | `500` | `14.068 files/s` |

Native was only slightly faster in k3s and slower in GKE.

---

## Slide 9 - Architectural Takeaway

Proxy readers should remain the default.

That keeps the clean responsibility boundary:

| Component | Responsibility |
| --- | --- |
| Connector | Repository credentials, enumeration, object identity, source-specific reads. |
| DSX-Connect | Durable jobs, queueing, scanning workflow, policy, remediation, reporting. |
| DSXA | File analysis and verdicts. |

Native readers can remain an advanced option for specific deployments.

They should not become the primary model unless a deployment proves a meaningful benefit.

---

## Slide 10 - What The GKE Test Showed

The GKE full-stack benchmark was slower than the k3s lab benchmark.

That is useful data.

The measurements pointed away from GCS reader strategy as the primary bottleneck:

- proxy reader time was near zero
- queue wait was significant
- DSXA request wall time dominated
- Postgres, RabbitMQ, relay, and policy workers were visibly active
- DSXA logs showed intermittent chunked request read exceptions

The next tuning target is full-stack deployment shape, not native readers.

---

## Slide 11 - Operational Improvements Over 1G

DSX-Connect 2 gives operators more than a faster scan.

It adds:

- durable scan jobs
- job cancellation
- protected scope tracking
- connector health and inventory visibility
- scan sample inspection
- scan statistics
- scan comparison
- CSV export for benchmark analysis
- richer `X-Custom-Metadata` sent to DSXA

This makes performance explainable.

---

## Slide 12 - Richer Scan Context

DSXA scan metadata now carries context such as:

- source
- object identity
- integration ID
- integration name
- platform
- platform key
- scope ID
- scope selector
- job ID
- job item ID
- reader strategy
- connector endpoint when proxy is used

This links DSXA results back to DSX-Connect jobs and protected assets.

---

## Slide 13 - The Main Message

The performance story is:

```text
2G is materially faster than 1G
because batch scanning and worker orchestration improved
the end-to-end workflow shape.
```

The architecture story is:

```text
2G gets those gains while preserving persistence,
operator visibility, and the connector abstraction.
```

That is the important outcome.

---

## Slide 14 - Recommended Position

Default posture:

- use connector proxy reads
- keep repository credentials in connectors
- keep DSX-Connect core repo-agnostic
- use batch scanning as the primary performance model
- tune workers, RabbitMQ, PostgreSQL, relay, and DSXA capacity
- use native readers only as measured, deployment-specific optimizations

This gives us performance without trading away the platform boundary.

---

## Slide 15 - Next Benchmark Questions

The next useful tests are deployment-shape tests:

- GKE resource requests and limits
- DSXA replicas and CPU/memory sizing
- PostgreSQL and RabbitMQ sizing
- scan worker count and scan batch concurrency
- relay active item cap
- policy worker prefetch
- bucket region versus cluster region

The question is no longer whether native readers are required.

The question is how to size and tune the durable full-stack pipeline.
