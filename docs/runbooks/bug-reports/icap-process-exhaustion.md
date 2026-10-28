# Bug: ICAP process exhaustion under connection churn

Oct 20, 2026 · @Logan

## Summary and impact

Under connection churn, a single ICAP pod forks past the platform's per-pod process limit and returns ICAP 500s and dropped connections instead of throttling. Severity: High.

- **Affected:** DSX/A Scanner 4.3.0.2348 ICAP (connected build, images of Oct 18 2026), RESPMOD over TLS. Likely any build using the same fork-per-connection ICAP server.
- **Impact:** clients that open a new connection per file (common in load tests and some proxies) get ICAP 500 "Classification Failed", TCP resets and broken pipes. With the default 4-core CPU limit the same load instead causes 30–56 s queueing and client read timeouts.
- **Customer case:** found while reproducing a customer ICAP load-test ticket that uses `aggressive_tls_socketing: true` (a new TLS connection per file).

## Environment and steps to reproduce

| Item | Value |
| --- | --- |
| Scanner | 4.3.0.2348 connected images (built Oct 18 2026), Helm chart 4.3.0.2348 |
| Platform | OpenShift 4.22, single node, 24 vCPU and 96 GB; kubelet `podPidsLimit` 4096 (default) |
| ICAP | `icap.secure.ssl_on_icap_pod: true`, port 1344, one replica, CPU limit 8 cores (4 cores reproduces the timeout variant) |
| Client | Python ICAP load client in a pod on the same cluster, calling the ICAP service directly |

1. Deploy ICAP with one replica and TLS on, and raise its CPU limit to 8 cores.
2. Run 100 concurrent clients for 120 s. Each sends RESPMOD on `/response` with a clean file of 17 B to 2.2 MB, opening a new TCP + TLS connection per file and closing it after the response.
3. Watch the pod's process count: `cat /sys/fs/cgroup/pids.current` in the `dpa` container of the ICAP pod.
4. Check the ICAP log and the client error counts.

## Expected vs actual

**Expected:** every request gets a verdict. Under overload the server queues requests or returns ICAP 503, and never fails mid-request.

**Actual:** the pod reaches about 4,050 processes within 10 s and holds there. Process creation then fails.

| Configuration (120 s, 100 clients, new TLS connection per file) | Files / s | Max latency | Client errors | Peak pod processes |
| --- | --- | --- | --- | --- |
| 1 pod, 8-core limit | 120 | 32.2 s | 107 ICAP 500, 301 broken pipes, 180 TCP resets | about 4,050 |
| 1 pod, 4-core limit | 94 | 55.9 s | 12 read timeouts (60 s); CPU pinned at 4.0 cores | not sampled |
| 3 pods, 4-core limit each | 206 | 7.2 s | none | 2,724 |

ICAP log lines during the 8-core run (counts over 120 s):

```
426  BlockingIOError: [Errno 11] Resource temporarily unavailable
107  Classifier failed handling file. Error: Resource temporarily unavailable
104  Exception was thrown: [Errno 32] Broken pipe
 83  ../Client/ClassifierPython/ClassifierPython.cpp:268: Failed to fork, errno: 11
 75  ../Client/Classifier/src/Classifier/KtCurl.cpp:390: failed to perform curl request. result: 6.
```

## Root cause, workaround and suggested fix

The ICAP server forks per connection with a child cap (5,000) above the platform's per-pod process limit (4,096), so it never throttles before `fork()` fails.

- `icap_server/di_icap_server.py` serves with `ForkingWithAtomicMixIn(socketserver.ForkingMixIn)`, `max_children = 5000` (and `max_active_children = 5000`).
- The classifier forks again per scan (`ClassifierPython.cpp:268`), so live processes run well above the number of in-flight requests.
- A failed fork raises `EAGAIN`; the handler turns it into ICAP 500 "Classification Failed" or drops the connection.

**Workaround:** run several ICAP replicas or enable HPA (`icap.min_replicas`, `icap.hpa_enabled`), and have clients reuse connections. One pod with persistent TLS connections ran at 185 files/s with no errors.

**Suggested fix:**

1. Derive the child cap from the container's effective process limit (the pod's cgroup `pids.max`), leaving headroom for classifier forks.
2. At the cap, queue new connections or answer ICAP 503 instead of failing mid-request.
3. Consider a bounded worker pool or threads for TLS connections instead of fork-per-connection, and reap exited children promptly.
4. Document per-pod concurrency sizing for ICAP and recommend HPA.
