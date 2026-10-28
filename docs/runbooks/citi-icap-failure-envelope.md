# DSX/A ICAP at 2 CPU: which client settings cause failures

Oct 23, 2026 · Deep Instinct

## Summary

On one DSX/A ICAP pod limited to 2 CPU and 16 GB, the test client caused failures from **100 workers** when it opened a new TLS connection per file (`aggressive_tls_socketing: true`), and from **200 workers** with persistent connections. Below those levels every file was scanned without a timeout or error.

- **Failures were timeouts, not errors.** No run returned an ICAP error, and the scanner never restarted. Requests waited longer than the client's 60 s limit for a connection or a response.
- **The client's retries hid every failure.** Every timed-out file succeeded on a later attempt (0 dropped requests). A client that doesn't retry correctly would fail each of those transfers.
- **CPU was the limit.** From 50 workers up, the pod used its full 2 CPU in every run. With a new connection per file, adding workers beyond 50 *lowered* throughput, because more CPU went to setting up TLS connections.
- **Bursts matter as much as steady load.** Many timeouts were on each worker's *first* file, when all workers connected at the same moment: 15 of 38 timeouts at 100 workers, and 76 of 148 at 200.

## Results (2 CPU, 16 GB, one pod)

Each run lasted 120 s with the test client's configuration as supplied, changing only the number of workers and `aggressive_tls_socketing`. Other settings: RESPMOD over TLS, 60 s connection and read timeouts, 3 retries, 15 sample files from 17 B to 2.2 MB.

**New TLS connection per file (`aggressive_tls_socketing: true`)**

| Workers | Files / s | MB / s | Avg / max latency | Read timeouts | Connection timeouts | Dropped | Peak CPU |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | **54** | 16.2 | 0.46 s / 10.2 s | 0 | 0 | 0 | 1.67 |
| 50 | **69** | 20.5 | 0.69 s / 31.9 s | 0 | 0 | 0 | 2.00 (limit) |
| 100 | **54** | 15.8 | 1.31 s / 56.7 s | **38** | 0 | 0 | 1.94 |
| 200 | **46** | 13.0 | 1.98 s / 60.6 s | **148** | **31** | 0 | 1.91 |

**Persistent connections (`aggressive_tls_socketing: false`)**

| Workers | Files / s | MB / s | Avg / max latency | Read timeouts | Connection timeouts | Dropped | Peak CPU |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | **60** | 18.0 | 0.41 s / 3.5 s | 0 | 0 | 0 | 1.11 |
| 50 | **97** | 29.2 | 0.50 s / 4.0 s | 0 | 0 | 0 | 1.70 |
| 100 | **103** | 30.7 | 0.87 s / 5.8 s | 0 | 1 | 0 | 2.00 (limit) |
| 200 | **104** | 30.3 | 1.57 s / 34.6 s | 0 | **32** | 0 | 2.00 (limit) |

With persistent connections, all connection timeouts happened at the start of the run, when 200 workers opened their connections simultaneously. After that, no request timed out.

For comparison, from our earlier tests at 100 workers with a new connection per file:

| Configuration | Files / s | Result |
| --- | --- | --- |
| 1 pod, 2 CPU | 54 | 38 read timeouts |
| 1 pod, 4 CPU | 94 | 12 read timeouts; CPU at the limit |
| 1 pod, 8 CPU | 120 | 107 ICAP 500 errors and connection resets; the pod reached its process limit |
| 3 pods, 4 CPU each | 206 | No errors |
| 1 pod, 4 CPU, persistent connections | 185 | No errors |

Adding CPU to a single pod moves the failure point but doesn't remove it. Above about 4 CPU, the failure changes from timeouts to errors. Spreading the load over several pods removed the failures.

## What it takes to cause failures

1. **Enough concurrent workers for the available CPU.** At 2 CPU: 100 workers with a new connection per file, or 200 with persistent connections.
2. **New TLS connections per file.** Each file costs a TLS handshake and a new scanner process. At the same CPU, persistent connections handled about 1.5 to 2 times the files per second, with far lower worst-case latency.
3. **Many connections opened at once.** A burst of simultaneous new connections (for example, many transfers starting together) queues at the scanner. Some wait longer than the client's timeout even when the average load is sustainable.
4. **A client timeout shorter than the worst-case wait.** Worst-case latency reached 32 s at only 50 workers with a new connection per file. A client timeout of 30 s would have failed there.
5. **A client that doesn't retry correctly.** With retries, no file was lost in any run. Without them, every timeout above is a failed transfer.

## Why Citi's environment may fail sooner than ours

Our test pod ran on a node with spare capacity, so it always got its full 2 CPU. These differences could make Citi's environment fail at lower load. We'd welcome the details to compare:

| Factor | Our test | Question for Citi |
| --- | --- | --- |
| CPU actually available | 2 CPU limit, always available. The default CPU *request* is 0.5 CPU. | On a busy shared node, a pod is only guaranteed its request, so it may get much less than 2 CPU. What are the pod's CPU request and limit, and does it show CPU throttling under load? |
| Connection bursts | Every worker connects at the start of the run. | How many transfers does Secure Transport start at the same moment? |
| Client timeouts and retries | 60 s connection and read timeouts, 3 retries. | What ICAP timeouts does Secure Transport use, and does it retry? |
| Files | 15 samples up to 2.2 MB. | What are the typical file sizes and types? |
| Network path | Client in the same cluster, connecting straight to the scanner's service. | Is there a load balancer or TLS-terminating proxy in between, and what latency does it add? |
| Outbound access | The scanner reaches Deep Instinct's cloud for reputation lookups directly. | Does the scanner reach the internet through a proxy? Slow lookups add to scan time. |

## Recommendations

1. **Set the CPU request equal to the limit** (for example 4 CPU each), so the scanner gets its CPU even on a busy shared node.
2. **Scale out rather than up.** Run two or more ICAP pods, or enable autoscaling (`icap.min_replicas`, `icap.hpa_enabled`), instead of giving one pod more CPU.
3. **Use persistent connections** where Secure Transport supports them, and avoid starting large numbers of transfers at the same moment.
4. **Set client timeouts and retries deliberately.** Make the ICAP timeout longer than the expected worst case under peak load, and retry on timeout.
