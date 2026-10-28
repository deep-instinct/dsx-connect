# Bug: Reputation lookups time out under load

Oct 20, 2026 · @Logan

## Summary and impact

Under moderate ICAP load, about 90% or more of the scanner's cloud reputation (DCloud) lookups time out after 3 attempts, and scans return a verdict without the reputation result. Severity: Medium.

- **Affected:** DSX/A Scanner 4.3.0.2348 connected build (images of Oct 18 2026), ICAP over TLS; the REST path was not load-tested.
- **Impact:** files that need a reputation check (the two ELF binaries in our set; the PE32 sample had no failures) are classified without it, and each failed lookup adds latency. Nothing tells the client or the console that the check was skipped.
- **Load level:** 94 to 206 files/s from 100 concurrent clients, on one or three ICAP pods. Single scans of the same files show no failures.

## Environment and steps to reproduce

| Item | Value |
| --- | --- |
| Scanner | 4.3.0.2348 connected images (built Oct 18 2026), registered to a DSX console |
| Platform | OpenShift 4.22 on Google Cloud, single node; outbound internet through the cluster's default egress |
| ICAP | TLS on port 1344; 1 pod (4- or 8-core CPU limit) or 3 pods |
| Files | 15 clean samples, including `file4.elf64` (SHA-256 `1e39354a…736d`) and `file5.elf32` (SHA-256 `0a6b7dca…4f04`) |

1. Scan `file4.elf64` once over ICAP RESPMOD. It returns 204 in about 0.15 s with no DCloud errors in the ICAP log.
2. Run 100 concurrent ICAP clients for 120 s over the 15 files, so each ELF file is scanned 800 to 1,700 times.
3. Count `Failed to get an answer from DCloud` lines in the ICAP pod logs and group them by hash.

## Expected vs actual

**Expected:** reputation lookups succeed under load, or are answered from a cache for a hash already looked up seconds earlier.

**Actual:** nearly every scan of the two ELF files fails its lookup, in every load configuration.

| Run (120 s, 100 clients, TLS) | Files / s | DCloud lookup failures | ELF scans failing (approx.) |
| --- | --- | --- | --- |
| 1 pod, 4 cores, new connection per file | 94 | 1,550 | 90% |
| 1 pod, 4 cores, persistent connections | 185 | 3,024 | 92% |
| 1 pod, 8 cores, new connection per file | 120 | 1,886 | 93% |
| 3 pods, 4 cores each, new connection per file | 206 | 3,328 | 99% |

The share is estimated from total scans, since each of the 15 files is sent equally often. Every failure names one of the two ELF hashes. A representative log line:

```
E ../Client/Classifier/src/Classifier/KnownThreats.cpp:432: Failed to get an answer from DCloud, made 3 attempts using this hash 1e39354a6e481dac48375bfebb126fd96aed4e23bab3c53ed6ecf1c5e4d5736d. last error: REQUEST_CURLE_TIMEOUT
```

All scans still returned 204. In the 8-core run, 75 lookups also failed with `failed to perform curl request. result: 6` (could not resolve host) while the pod was out of processes.

## Analysis and suggested fix

The failures track concurrent lookups of the same hash; scanner CPU was not the limit, since three pods with spare CPU failed the most. The exact cause needs Deep Instinct's view of the DCloud request path.

- The failure rate rose with throughput (90% at 94 files/s to 99% at 206 files/s), even with three pods and spare CPU.
- Only two hashes were involved, so each failure was a repeat lookup of a hash already queried moments before. Either results are not cached across scans, or concurrent requests for one hash are not merged.
- Possible causes to check: a short curl timeout under concurrency, server-side rate limiting of repeated requests, or limits on outbound connections from the pod.

**Suggested fix:**

1. Cache reputation results per hash for a short period, and merge concurrent lookups of the same hash into one request.
2. Review the curl timeout and the 3-attempt retry budget under concurrency, and use backoff between attempts.
3. Report skipped reputation checks, for example as a field in the verdict or a counter in metrics, so operators can see them.
4. Check whether the DCloud service throttles one scanner's repeated requests, and document the expected lookup rate per scanner.
