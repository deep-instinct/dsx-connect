# Connector Batch Benchmark Summary

This page summarizes local benchmark runs that compared traditional single-item full-scan enqueue against batched enqueue.

The goal of these runs was not to prove a single universal throughput number.
The goal was to identify whether connector-to-core handoff was a meaningful bottleneck across connector types.

## Test Shape

All runs were performed on a local development setup using the same core API path:

* Baseline: `POST /dsx-connect/api/v1/connectors/full_scan/{connector_uuid}`
* Batch: `POST /dsx-connect/api/v1/connectors/full_scan/{connector_uuid}?batch=true&batch_size=100`

The key comparison points were:

* Enqueue time
* End-to-end job time
* Whether `enqueued_count`, `enqueued_total`, `processed_count`, and `terminal_count` remained consistent

## Results

| Connector | Corpus | Baseline Enqueue | Baseline Total | Batch Enqueue | Batch Total | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Filesystem | `1002` | about `78-80s` | about `78-80s` | about `1.5s` | about `33s` | Local folder scan |
| Azure Blob Storage | `1207` | `8m08s` | `8m12s` | `27s` | `7m37s` | Real accepted total after counting fix |
| SharePoint (Graph) | `1026` | `80s` | `110s` | `1s` | `49s` | Strong total improvement |
| Google Cloud Storage | `1002` | `179s` | `180s` | `11s` | `159s` | Big enqueue win, modest total win |
| OneDrive | `998` | `122s` | `167s` | `2s` | `53s` | `4` files failed upload before scan |

## What Changed

These runs validated two important changes:

### 1. Batch enqueue materially reduces connector-to-core handoff cost

Across every connector tested, batch mode dramatically reduced enqueue time.

This means the older one-file-at-a-time handoff was a real bottleneck, not just a connector-specific implementation detail.

### 2. Progress counting should be owned by core

During this work, optimistic connector-side counting caused mismatches between:

* files a connector believed it had queued
* files core had actually accepted

The benchmark work moved visible progress to core-owned accepted counts so that:

* `enqueued_count`
* `enqueued_total`
* `processed_count`
* `terminal_count`

reflect the real queue lifecycle rather than connector guesses.

## Main Takeaway

Batching consistently removes a large portion of the connector-side overhead.

After batching is enabled, the dominant bottleneck usually shifts downstream to one or more of:

* connector `read_file` throughput
* scan-request worker throughput
* DSXA scan capacity
* network bandwidth
* remote provider API latency

So batching is not the whole performance story.
It is the handoff optimization that exposes the next real bottleneck.

For `dsx_connect_ng` local batch scans, deferred publish should be treated as the operational default.
The API should persist the batch and item outbox first, and the relay should publish scan work only up to the configured active-item cap.
This keeps API calls and cancellation responsive when a batch contains thousands of items.

Use inline publish only for small diagnostic runs that intentionally test immediate queue publication.

## NG Batch Scan Findings

Follow-up `dsx_connect_ng` tests used a `1003` file local corpus under `/Users/logangilbert/Documents/SAMPLES/1kdocs`.

Direct DSXA SDK scanning against the same corpus showed the scanner and SDK path are not the limiting factor:

| Path | Concurrency | Result |
| --- | ---: | ---: |
| Direct Python SDK `scan-folder` | `1` | `1003` files in `32.52s`, about `30.84 files/s` |
| Direct Python SDK `scan-folder` | `4` | `1003` files in `9.39s`, about `106.77 files/s` |
| Direct Python SDK `scan-folder` | `8` | `1003` files in `7.19s`, about `139.54 files/s` |
| Direct Python SDK `scan-folder` | `10` | `1003` files in `7.10s`, about `141.24 files/s` |
| Direct Python SDK `scan-folder` | `16` | `1003` files in `7.07s`, about `141.88 files/s` |

The NG scan-worker direct path, which bypasses API/Postgres/RabbitMQ/relay/job persistence but uses the same NG reader and DSXA execution code, showed a practical local ceiling around `130 files/s`:

| Path | Concurrency | Elapsed | Throughput | DSXA avg | DSXA p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| NG direct scan-worker benchmark | `4` | `10.029s` | `99.711 files/s` | `38.989ms` | `83.637ms` |
| NG direct scan-worker benchmark | `6` | `7.893s` | `126.702 files/s` | `45.726ms` | `98.141ms` |
| NG direct scan-worker benchmark | `8` | `7.577s` | `131.973 files/s` | `58.441ms` | `122.329ms` |
| NG direct scan-worker benchmark | `12` | `7.657s` | `130.600 files/s` | `88.453ms` | `168.379ms` |
| NG direct scan-worker benchmark | `16` | `7.732s` | `129.329 files/s` | `118.882ms` | `201.158ms` |

That direct benchmark knees around `8` concurrent scans on the local host.
Higher concurrency does not improve throughput and mainly increases DSXA wait latency, which points to scanner-side queueing or local resource contention rather than reader I/O.

The equivalent NG batch path initially remained around `3-4 files/s` after removing connector temp-file staging and after adding a scan-only fast path.
That meant the remaining gap was in NG orchestration rather than DSXA scanning.

After removing scan-only per-item durable orchestration writes from the hot path, the same NG batch path reached about `29.5 files/s`:

| Path | Corpus | Result |
| --- | ---: | ---: |
| NG scan-only batch, before hot-path write reduction | `1000` files | about `3-4 files/s` |
| NG scan-only batch, after hot-path write reduction | `1000` files | `599` terminal items at about `29.58 files/s`; `895` terminal items at about `29.55 files/s` |

The throughput improvement came from removing synchronous database work that was more expensive than the actual scan for small files:

* skipped the per-item durable `scan_stage=running` update for scan-only jobs
* skipped policy, DIANNA, remediation, and delivery outbox work for scan-only jobs
* completed scan-only items with one stage update instead of a scan update plus follow-on workers
* stopped refreshing the parent job after each scan-only item completion
* stopped refetching each item after scan-only completion

This is now tied to the job recovery model rather than being only a benchmark trick:

* default `batch` recovery uses coarse durable scan progress for scan-only work
* `recovery_mode="item"` keeps the per-item durable `running` transition for maximum recovery fidelity
* explicit scan progress modes can force `coarse` or `item` behavior on a scan request

Live operator visibility now uses runtime scan leases:

* scan workers mark a lightweight runtime lease while an item is actively being scanned
* the progress API reports `runtime.scan_leases_active`
* progress backlog overlays that value into `backlog.scanning`
* these leases are intentionally ephemeral and are not the durable recovery contract

With those changes, DSXA request wall time returned to the expected range for this corpus, around `50ms` average with engine time in the tens of milliseconds.

Further scan-only batching work moved the local full-stack path to the `65-67 files/s` range:

| Path | Shape | Result |
| --- | --- | --- |
| NG full stack, native reader, scan-only, deferred publish | `4` scan workers x `2` scan concurrency | `1000` files in `15.054s` progress elapsed, `66.427 files/s` progress throughput, `67.139 files/s` after submit, `64.876 files/s` total |

This run used Postgres, RabbitMQ, relay, scan workers, and native filesystem reader.
The relay wake path used Postgres `NOTIFY`, and relay refill no longer inserted waits between non-empty publish flushes.
Relay evidence from the run showed one `relay_wakeup.notified=true` before the first job flush, then `10` consecutive non-empty publish flushes for `1000` records with no wake wait between them.
Average relay publish time per `100` records was about `187ms`.

At this point relay refill is no longer the main cap.
The remaining gap between full stack (`~67 files/s`) and direct NG scan-worker (`~130 files/s`) is in scan worker orchestration, RabbitMQ delivery, scan-only completion persistence, and Python scheduling around the worker pool.

The scan-only completion path was then changed from row-by-row `executemany` updates to one set-based `UPDATE ... FROM (VALUES ...)` statement, and scan workers stopped refreshing the parent job after every completion flush.
Parent job state remains derived from item state and is refreshed by progress/final observation when all items are terminal.

This significantly reduced completion persistence timing, but did not immediately improve 1000-file end-to-end throughput in the local stack:

| Path | Completion flush avg | Completion flush p95 | End-to-end observation |
| --- | ---: | ---: | --- |
| Before set-based completion | `177.6ms` | `220.8ms` | `67.555 files/s` after submit in one run |
| After set-based completion and deferred parent refresh | `15.7-19.4ms` | `24.5-41.3ms` | follow-up runs landed between `53.8-62.1 files/s` after submit because relay publish and DSXA wait latency rose |

The important conclusion is that scan-only completion persistence is no longer the measured hot spot in those follow-up runs.
One post-change run showed relay publish averaging `377.5ms` per `100` messages, and another showed DSXA wait p95 above `2s`; those effects dominate the remaining local variance.

Enabling trusted scan-batch items then removed the remaining per-item DB reads around scan start and completion.
In trusted mode, the scan worker treats the RabbitMQ scan message as already-valid accepted item intent and skips the pre/post `get_job_item` and cancellation checks inside the pooled scan hot path.
This is appropriate for coarse scan-only recovery, where the durable contract is accepted item membership plus terminal outcomes.
Strict item-level recovery can still disable it with `--no-scan-batch-trust-items`.
The cancellation behavior is intentionally coarser in this mode: cancel should stop new publish/claim work, but files already claimed into an in-memory scan batch may finish before the cancel is fully reflected.
Immediate file-level cancel requires per-item tracking/checks in the scan hot path, which is expensive for the common path and usually not worth paying for the rare case where an operator cancels an active scan.

| Path | Shape | Result |
| --- | --- | --- |
| NG full stack, native reader, scan-only, deferred publish, trusted items | `4` scan workers x `2` scan concurrency | `1000` files in `10.920s` progress elapsed, `91.571 files/s` progress throughput, `93.871 files/s` after submit, `88.720 files/s` total |

The trusted-items run completed `1000/1000` items with no failures.
Completion flushes remained cheap: `60` flushes, average `17.605ms`, p95 `40.868ms`.
Relay publish was back in the normal range: `10` flushes of `100`, average `196.936ms` publish time per `100`.
This is the strongest local evidence that per-item DB read/check overhead was still a meaningful hot-path cost after completion persistence was optimized.

Important observations:

* RabbitMQ scan workers are event-driven once work reaches RabbitMQ.
* The deferred Postgres outbox to RabbitMQ relay is currently poll-driven.
* Default relay polling (`5s`) can leave the active scan window underfilled.
* Scan-only fast path keeps `policy_pending`, remediation, and delivery at zero, confirming policy/result-sink are no longer the measured bottleneck for scan-only tests.
* Per-item synchronous Postgres updates in the scan hot path are too granular for high-throughput small-file batches.
* Scan-only completion persistence must use real set-based bulk updates, not one `UPDATE` per item hidden behind `executemany`.
* For coarse scan-only batches, scan workers should trust accepted scan messages by default and avoid pre/post per-item DB reads.
* Trusted batch cancellation is cooperative rather than immediate at file granularity; use strict item-level mode when immediate cancellation is more important than throughput.
* Parent job state should remain a derived summary for scan-only batch completion and should not be refreshed on every small completion flush.
* Parent job state can be refreshed when a batch is observed complete, not after every item.

The resilience/performance tension is now explicit:

* Durable state is required for accepted job intent, accepted item membership, terminal scan results, and remediation obligations.
* Transient states such as `queued`, `running`, and fine-grained stage edges should not require synchronous durable writes for every item if the goal is high throughput.
* Batch scans should eventually persist durable checkpoints and terminal outcomes in bulk, while using runtime counters or leases for in-flight progress.
* For scan-only/full-scan style workloads, rescanning an uncheckpointed in-flight batch after a crash is acceptable. The durable contract is accepted work plus terminal outcomes, not every transient edge.

Near-term direction:

1. Keep deferred publish as the default for large batch scans.
2. Wake the relay immediately when new outbox rows are committed, using polling only as a fallback.
3. Continue publishing only up to an active-item cap so cancellation remains responsive.
4. Keep scan-only progress parent refresh deferred to progress reads or batch completion.
5. Keep scan-only completion writes set-based.
6. Default trusted scan-batch items for coarse scan-only recovery; use `--no-scan-batch-trust-items` for strict item-level cancellation/recovery checks.
7. Document operator-facing cancel semantics clearly: cancel stops future work quickly, while already claimed in-memory batch items may complete.
8. Add runtime counters/metrics if operators need live `queued`/`scanning` visibility without restoring synchronous durable writes.

Current local test command:

```bash
dsx-connect-ng-local \
  --with-postgres-docker \
  --with-rabbit-docker \
  --scan-worker-count 4 \
  --scan-worker-prefetch-count 1000 \
  --scan-batch-window-size 100 \
  --scan-batch-window-wait-seconds 0.5 \
  --scan-batch-concurrency 2 \
  --scan-batch-ack-mode scanned \
  --scan-batch-trust-items \
  --no-scan-only-runtime-leases \
  foreground
```

Current validator command:

```bash
./.venv/bin/python scripts/validate_ng_batch_proxy_reader.py \
  --reader-strategy native \
  --scan-only \
  --sample-dir /Users/logangilbert/Documents/SAMPLES/1kdocs \
  --use-existing-samples \
  --item-count 1000 \
  --submit-timeout-seconds 600 \
  --poll \
  --poll-mode progress \
  --poll-timeout-seconds 3600 \
  --poll-interval-seconds 1
```

Expected diagnostic caveat: scan-only progress may show `scanned: 0`, `scan_stage_ms: null`, and `queue_wait_ms: null` because those depended on transient durable stage updates that were intentionally removed from the hot path.
Live in-flight scans should instead be visible via `runtime.scan_leases_active` and `backlog.scanning`.

## Final Local Scan-Only Tuning Baseline

The local launcher has two relevant scan-worker concurrency layers:

* `--scan-worker-count`: number of scan worker processes
* `--scan-batch-concurrency`: number of concurrent DSXA scans inside each scan-only batch coordinator

Total scan concurrency is approximately:

```text
scan_worker_count * scan_batch_concurrency
```

These are not interchangeable:

* Higher per-worker scan concurrency is cheaper and should perform well while the bottleneck is async scanner I/O.
* More worker processes add Python process overhead but can help if one event loop, one HTTP client pool, or CPU-bound reader work becomes the bottleneck.
* RabbitMQ prefetch must be high enough to keep each worker's local batch window and scan slots full.

The strongest local baseline after trusted scan-batch items is:

```bash
LOG_LEVEL=INFO \
DSX_CONNECT_NG_LOCAL__SCAN_BATCH_ITEM_LOGGING=false \
DSX_CONNECT_NG_LOCAL__WORKER_ACK_LOGGING=false \
./.venv/bin/python -m dsx_connect_ng.local.dsx_connect_ng_local \
  --with-postgres-docker \
  --with-rabbit-docker \
  --scan-worker-count 4 \
  --scan-worker-prefetch-count 1000 \
  --scan-batch-window-size 100 \
  --scan-batch-window-wait-seconds 0.5 \
  --scan-batch-concurrency 2 \
  --scan-batch-ack-mode scanned \
  --scan-batch-trust-items \
  --no-scan-only-runtime-leases \
  foreground
```

With the `1kdocs` corpus this shape completed `1000/1000` items with no failures and reached:

| Corpus | Worker processes | Scan concurrency per worker | Total scan concurrency | Progress elapsed | After-submit throughput | Total throughput |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `1kdocs` | `4` | `2` | `8` | `10.920s` | `93.871 files/s` | `88.720 files/s` |

With the larger `/Users/logangilbert/Documents/SAMPLES/10kdocs` corpus, which currently contains `9663` files, the same `4 x 2` shape amortized startup and poll jitter better:

| Corpus | Worker processes | Scan concurrency per worker | Total scan concurrency | Progress elapsed | After-submit throughput | Total throughput | Recent 60s at finish |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `10kdocs` | `4` | `2` | `8` | `85.532s` | `117.216 files/s` | `112.311 files/s` | `127.267 files/s` |

A follow-up `4 x 3` run did not improve throughput:

| Corpus | Worker processes | Scan concurrency per worker | Total scan concurrency | Progress elapsed | After-submit throughput | Total throughput | Recent 60s at finish |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `10kdocs` | `4` | `3` | `12` | `90.604s` | `110.749 files/s` | `106.040 files/s` | `119.083 files/s` |

The `4 x 3` run completed `9663/9663` with no failures, but it raised final sampled DSXA wall time to about `150.8ms` average and `227.7ms` p95.
The prior `4 x 2` 10k run finished faster, with final sampled DSXA wall time around `103.9ms` average and `215.4ms` p95.

DSXA container stats during the `4 x 3` run showed memory was not the limiting resource:

| Metric | Value |
| --- | ---: |
| DSXA CPU average | `381.673%` |
| DSXA CPU p50 | `440.340%` |
| DSXA CPU p95 | `483.470%` |
| DSXA CPU max | `489.630%` |
| DSXA memory average | `2.675 GiB` |
| DSXA memory p95 | `2.703 GiB` |
| DSXA memory max | `2.737 GiB` |
| Docker memory limit | `11.680 GiB` |

Earlier `4 x 2` DSXA stats had the same shape: CPU near the local ceiling and memory flat around `2.7 GiB`.
The local DSXA container and Helm values have no explicit resource limits; the effective local ceiling is the Docker/Colima allocation, which was `6` CPUs and about `11.68 GiB` memory.

The local conclusion is:

* `4` scan workers x `2` scan concurrency is the current single-DSXA local sweet spot.
* Increasing per-worker scan concurrency to `3` adds DSXA wait/queueing and regresses throughput.
* Memory is not the local bottleneck.
* DSXA CPU and scanner-side admission/execution capacity are the likely local limit.
* Further local code tuning is unlikely to produce a large jump without changing the scanner topology or available CPU.

Remaining useful experiments:

* Increase Docker/Colima CPU allocation and rerun `4 x 2`; if throughput rises, the local limit is confirmed as CPU-side scanner capacity.
* Test multiple DSXA pods behind a load balancer in cluster deployment. That is the expected path past the current single-DSXA local knee.

For future tuning runs, continue capturing total files/sec, `runtime.scan_leases_active`, `backlog.publish_pending`, `backlog.queued`, DSXA request latency, and DSXA container or pod CPU/memory.

## Architectural Implication

These results support a future cursor-plus-batch model:

1. Connector returns the next batch and a cursor.
2. Core accepts the batch.
3. Core updates accepted counts.
4. Core requests the next batch until enumeration completes.

That model keeps:

* discovery in the connector
* accepted-count ownership in core
* terminal-state ownership in workers/results

which is a cleaner design than connector-owned optimistic totals.
