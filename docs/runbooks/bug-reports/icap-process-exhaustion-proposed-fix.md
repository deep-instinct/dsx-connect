# Proposed fix: ICAP process exhaustion (tested patch)

Oct 22, 2026 · @Logan · follow-up to "ICAP process exhaustion under connection churn"

## Summary

A three-setting patch to `di_icap_server.py` removed every error in the ticket's load test on one pod. It also raised throughput from 119 to 164 files/s (35.6 to 49.3 MB/s).

Two problems combine to exhaust the pod's processes:

1. **Every child process sleeps 10 s after its connection closes.** At 119 files/s, about 1,480 idle children are alive at once.
2. **The server's existing connection queue never engages.** The child cap (5,000) is above the pod's process limit (4,096), and the listen backlog is the Python default of 5.

Shortening the linger removes the exhaustion. A correct cap and backlog keep latency bounded when load still exceeds capacity. No new component is needed on the customer side.

## Test results

Load: the customer's ICAP client, 100 workers, 120 s, RESPMOD over TLS, a new TLS connection per file (`aggressive_tls_socketing: true`), 15 clean files from 17 B to 2.2 MB. Server: one ICAP pod, 4.3.0.2348 connected image, 8-core CPU limit, pod process limit 4,096. Each variant ran the same image with only the settings below changed.

| Variant | Files / s | MB / s | ICAP 500 | Socket / IO errors | Avg / max latency | Peak pod processes | Live ICAP children |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V0 shipped (cap 5,000, backlog 5, linger 10 s) | **119** | 35.6 | 124 | 510 | 716 ms / 68.2 s | 4,091 of 4,096 | 1,476 |
| V1 queue fix (cap 1,000, backlog 1,024, linger 10 s) | **94** | 28.1 | 0 | 0 | 1,036 ms / 8.1 s | 3,027 | 1,076 |
| V2 queue fix + 1 s linger | **164** | 49.3 | 0 | 0 | 600 ms / 3.5 s | 888 | 362 |
| V3 1 s linger only (cap 5,000, backlog 5) | **169** | 50.6 | 0 | 0 | 578 ms / 28.7 s | 881 | 380 |

V0 matches the original ticket reproduction (120 files/s, 107 ICAP 500s). Server-side, V0 logged 70 `Failed to fork` and 769 `Resource temporarily unavailable` lines. V1, V2 and V3 logged none. DCloud reputation timeouts appeared in every variant; that is a separate bug and is not affected by this fix.

What the variants show:

- **The 10 s linger is the cause of the exhaustion.** Children live about 12 s each (1,476 children at 119 files/s). Each child uses about 2.8 process slots (threads count toward the pod limit), so the pod runs out at roughly 1,450 children.
- **The queue fix alone (V1) stops all errors but costs throughput.** With a 10 s linger, 1,000 children allow only about 94 files/s. Excess connections wait instead of failing, so max latency drops from 68 s to 8 s.
- **A short linger alone (V3) is fast but leaves no protection.** The backlog of 5 overflows under bursts and clients wait for TCP retransmits, so max latency is 28.7 s. A bigger burst or a slower classifier would exhaust the pod again.
- **Both together (V2) give the best result:** about 38% more throughput than shipped, zero errors, and a max latency of 3.5 s.

## Event delivery with a shorter linger (tested)

The 10 s sleep exists "to let the event message be sent to the network service". Every scan, clean or malicious, sends one event over ZMQ from the ICAP child to the network service in the same container. The child's socket uses `LINGER 0`, so a message that hasn't been sent when the child exits is silently dropped.

Test: the same load (cap 1,000, backlog 1,024, clean files), with the network service's own scan counter (`ENABLE_SCAN_METRICS=true`) compared against the scans the server logged. The network service, not the child, sends detections on to the console, so this hop is the only one the linger affects.

| Linger | Files / s | Scans | Events received by network service | Lost |
| --- | --- | --- | --- | --- |
| 10 s (shipped) | 94.7 | 11,769 | 11,769 | 0 |
| **1 s** | **167.1** | **20,545** | **20,545** | **0** |
| 0 s (control) | 175.4 | 21,544 | 21,506 | 38, with no error logged |

At this load, 1 s is enough, and the 0 s control shows the test detects loss. The safety margin at heavier load or CPU contention is unknown. A product fix should replace the fixed sleep with an explicit flush, for example setting the event socket's `LINGER` to a few seconds and closing it before the child exits.

## Risks of changing the defaults

Changing only the defaults passes the load test, but introduces or exposes these problems:

| # | Risk | Evidence | Mitigation |
| --- | --- | --- | --- |
| 1 | **Idle persistent connections can take every slot.** There is no idle timeout (the handler never sets `timeout`), so a keep-alive connection holds a child as long as the client keeps it open. Once the cap is reached, the server stops accepting. | **Tested:** with 1,000 idle TLS connections held, every new connection timed out in the TLS handshake (30 s) for the whole 150 s hold. With cap 5,000 the same 1,000 idle connections had no effect (OPTIONS answered in 0.05 s). Shipped builds also fail, at about 1,450 idle connections (fork failure), so a cap of 1,000 lowers that threshold and turns errors into a silent hang. | Add an idle timeout between requests (for example 60 s). Make the cap configurable. Answer 503 instead of hanging when full. |
| 2 | **The liveness probe can't detect a hung server.** `check_pod_liveness.py` wraps `main()` in `try/except`, prints the error and exits 0, so a timeout counts as healthy. | **Observed:** no failed probe and no restart during the 150 s in which the server accepted nothing. Pre-existing, but the queue makes "alive but not serving" more likely. | Exit non-zero on exception, and probe with a timeout shorter than `timeoutSeconds`. |
| 3 | **Overload looks like a hang, not an error.** With a 1,024 backlog the kernel completes the TCP handshake, so clients and TCP health checks see the port as open while connections wait. | Inferred from the backlog behaviour and from risk 1. | Answer ICAP 503 when the queue wait exceeds a limit. Recommend ICAP `OPTIONS` health checks on load balancers. |
| 4 | **A cap without the linger fix lowers throughput.** Throughput is bounded by cap ÷ (linger + scan time). | **Tested:** cap 1,000 with the 10 s linger gave 94 files/s against 119 shipped. | Ship the cap only together with the linger (or flush) fix. |
| 5 | **Long scans and slow uploads hold slots longer.** Large archives or slow clients keep a child busy for the whole transfer and scan, which lowers effective capacity at the same cap. | Not tested; this load used files up to 2.2 MB. | Size the cap per deployment, and test with large files. |
| 6 | **Process limits differ by platform.** OpenShift defaults to 4,096 per pod; plain Kubernetes and Docker often have no limit, and hardened clusters may set 1,024. The container cannot detect the limit (`pids.max` reads `max`). | Observed `max` inside the container. | Expose the cap as a Helm value, documented as process limit × 0.7 ÷ 3. |
| 7 | **Event loss margin under heavier load.** | 1 s lost nothing at 167 files/s; 0 s lost 0.18%. | Explicit flush instead of a fixed sleep (see above). |
| 8 | **TLS handshake in the accept loop (unchanged).** One slow or stalled handshake blocks accepting for everyone, queued or not. | From code (`get_request` → `wrap_socket` in the parent); not tested. | Hand the handshake to the child (`do_handshake_on_connect=False`). |

## Root cause in code

`icap_server/di_icap_server.py` (4.3.0.2348):

- `ForkingWithAtomicMixIn.max_children = 5000`. `process_request` → `collect_children_` blocks in `waitpid` while `len(active_children) >= max_children`. While blocked, the server doesn't call `accept()`, so new connections wait in the kernel listen backlog. This queue exists already, but the cap of 5,000 can never be reached under a 4,096 process limit.
- `ICAPServer(TCPServer)` doesn't set `request_queue_size`, so the listen backlog is 5.
- `ForkingSimpleServer.shutdown_request` and `ForkingSimpleSSLServer.shutdown_request` call `time.sleep(10)` in every child after the response is sent, "to let the event message be sent to the network service".
- The overload 503 path (`Classification Overloaded`, `max_active_children = 5000`) has the same unreachable threshold.
- The container cannot read the pod's limit: `/sys/fs/cgroup/pids.max` inside the `dpa` container reads `max`, because Kubernetes applies `podPidsLimit` on the pod-level cgroup. The cap therefore has to be configured; it can't be detected.

## Proposed change

The patch used in the test. Defaults keep today's behaviour, so the change can ship safely and be tuned per deployment:

```python
class ForkingWithAtomicMixIn(socketserver.ForkingMixIn):
    max_children = int(os.environ.get('ICAP_MAX_CHILDREN', '5000'))
    request_queue_size = int(os.environ.get('ICAP_LISTEN_BACKLOG', '5'))

# in ForkingSimpleServer.shutdown_request and ForkingSimpleSSLServer.shutdown_request
            time.sleep(float(os.environ.get('ICAP_CHILD_LINGER_SECONDS', '10')))
```

Recommended product change:

1. **Replace the fixed 10 s sleep with an explicit flush of the event message,** with a short timeout (for example, ZMQ `linger` on close), so a child exits as soon as its event is sent. If a fixed sleep is kept, 1 s delivered every event at 167 files/s in our test (see "Event delivery").
2. **Default `max_children` to about 1,000 and expose it as a Helm value.** At about 2.8 process slots per child, that leaves headroom under the default 4,096 process limit. Document how to size it as process limit × 0.7 ÷ 3.
3. **Default the listen backlog to 1,024** (the node allows up to 4,096 via `net.core.somaxconn`).
4. **Use the same threshold for the `Classification Overloaded` 503 path** so it can actually trigger, and send the 503 before reading the body.
5. **Add an idle timeout on keep-alive connections** (risk 1), and **make the liveness probe fail on exceptions** (risk 2). Without these, a cap of 1,000 lets idle connections silently stop the server.
6. **Longer term:** move the TLS handshake out of the accept loop. `get_request` calls `wrap_socket(server_side=True)` in the parent, so handshakes run one at a time before forking. Then consider a fixed worker pool instead of fork-per-connection.

## Workaround until the fix ships

- **Scale ICAP replicas** (`icap.min_replicas` or `icap.hpa_enabled`). Three 4-core pods handled 206 files/s with no errors on the shipped image.
- **Limit the rate of new connections per ICAP pod at the existing load balancer** (for example an F5 pool member connection rate limit), to about 90 new connections per second per pod. A limit on *concurrent* connections does not help on the shipped image: the idle children are left over from connections that have already closed, so their number depends on the connection rate (about 12 s of life each), not on how many connections are open.
- **Reuse connections where the client allows it.** One pod with persistent TLS connections handled 185 files/s with no errors.
