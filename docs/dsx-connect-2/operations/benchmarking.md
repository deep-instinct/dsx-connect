# Benchmarking DSX-Connect 2

Use a layered benchmark so DSX-Connect 2 results can be compared fairly with older DSX-Connect 1G runs.

The goal is to separate:

* connector enumeration time
* connector proxy read time
* DSXA scan time
* queue and persistence overhead
* policy, remediation, and result delivery overhead

## Compare Equivalent Shapes

When comparing with 1G, keep these inputs consistent:

| Input | Guidance |
| --- | --- |
| Dataset | Use the same bucket, prefix, object count, and approximate byte mix. |
| DSXA scanner | Use the same scanner deployment and resources. |
| Connector | Record connector image version and replica count. |
| DSX-Connect | Record image/chart version, worker replicas, prefetch, and scan concurrency. |
| Result mode | Do not compare scan-only runs to policy/remediation workflow runs as if they are the same workload. |

Old 1G GCS batch reference from local benchmark work:

| Connector | Corpus | Batch enqueue | Batch total |
| --- | ---: | ---: | ---: |
| Google Cloud Storage | `1002` | `11s` | `159s` |

That is about `6.3 files/s` end to end.

## Run A DSX-Connect 2 Protected-Scope Benchmark

Start a protected-scope scan and watch it to completion:

```bash
export DSX_CONNECT_URL="https://dsx-connect.10.2.4.103.nip.io/api/v1"
export SCOPE_ID="<scope-id>"

./scripts/benchmark_ng_job.py \
  --api-base-url "$DSX_CONNECT_URL" \
  --scope-id "$SCOPE_ID" \
  --label "2G GCS protected scope" \
  --mode "2g-gcs-protected-scope" \
  --reader-strategy proxy \
  --limit 1000 \
  --poll-interval-seconds 5 \
  --progress-item-limit 1000 \
  --sample-items-limit 100 \
  --insecure \
  --output-json /tmp/dsx-connect-2-gcs-benchmark.json
```

Omit `--insecure` when the HTTPS certificate is trusted.

The script prints:

* progress events while the job runs
* final JSON summary
* a Markdown table row for benchmark notes

## Watch An Existing Job

If a scan is already running:

```bash
export JOB_ID="<job-id>"

./scripts/benchmark_ng_job.py \
  --api-base-url "$DSX_CONNECT_URL" \
  --job-id "$JOB_ID" \
  --label "2G GCS existing job" \
  --mode "2g-gcs-existing-job" \
  --poll-interval-seconds 5 \
  --progress-item-limit 1000 \
  --sample-items-limit 100 \
  --insecure
```

## Compare GCS Reader Throughput

Use the reader-only benchmark when the question is `proxy` versus `native` read speed. This benchmark streams bytes from the same GCS objects through each reader path without DSXA, RabbitMQ, policy, remediation, or result delivery in the measurement.

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.dsx-connect-local/google-cloud-storage-connector-2g/gcp-sa.json"

./scripts/benchmark_gcs_readers.py \
  --bucket lg-test-01 \
  --prefix benchmarks/1kdocs \
  --limit 1000 \
  --mode both \
  --proxy-endpoint http://127.0.0.1:8595/google-cloud-storage-connector/read_file \
  --concurrency 8 \
  --chunk-size 1048576 \
  --output-json /tmp/dsx-gcs-reader-benchmark-1000-c8.json
```

For lab runs, point `--proxy-endpoint` at the connector `read_file` endpoint reachable from the benchmark host. Native mode uses `GOOGLE_APPLICATION_CREDENTIALS` and reads GCS directly from the benchmark process.
DSX-Connect 2 reader chunk size is controlled by `DSX_CONNECT_NG_READERS__CHUNK_SIZE_BYTES`, defaulting to `1048576`.
The GCS connector accepts `DSXCONNECTOR_CHUNK_SIZE_BYTES`; the older `CHUNK_SIZE` environment variable remains supported for compatibility.

Local July 14, 2026 result against `lg-test-01/benchmarks/1kdocs`:

| Mode | Success | MiB Read | Elapsed sec | Items/sec | MiB/sec | Avg Read ms | P95 Read ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| native, before client cache | `988/988` | `101.748` | `112.695` | `8.767` | `0.903` | `900.567` | `1248.951` |
| proxy, before pooled/threaded transport | `988/988` | `101.748` | `122.604` | `8.058` | `0.830` | `991.269` | `1568.168` |
| raw `google.cloud.storage`, one shared client | `988/988` | `101.748` | `35.177` | `28.087` | `2.892` | `278.135` | `474.666` |
| raw connector `GCSClient.open_object_stream`, one shared client | `988/988` | `101.748` | `32.792` | `30.129` | `3.103` | `257.189` | `422.796` |
| raw connector `GCSClient.get_object`, one shared client | `988/988` | `101.748` | `20.868` | `47.345` | `4.876` | `165.952` | `353.109` |
| native, cached shared client | `988/988` | `101.748` | `30.177` | `32.740` | `3.372` | `235.665` | `421.421` |
| proxy, pooled NG HTTP + threaded connector read | `988/988` | `101.748` | `29.585` | `33.395` | `3.439` | `225.665` | `392.939` |

The first native run showed only a small advantage over proxy because it constructed a new Google SDK client per item. After caching the native GCS client per process, native read throughput moved into the same range as raw shared-client GCS reads. Proxy then reached the same range after two transport fixes: pooled async HTTP from NG to the connector, and moving connector-side blocking GCS stream reads off the connector event loop. Native still has architectural advantages because it removes a process hop, but this local corpus does not show a decisive reader-only advantage once proxy is optimized.

Native chunk-size sweep, same corpus and concurrency:

| Chunk size | Success | Elapsed sec | Items/sec | MiB/sec | Avg Read ms | P95 Read ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `262144` | `988/988` | `31.642` | `31.225` | `3.216` | `239.863` | `588.434` |
| `1048576` | `988/988` | `30.177` | `32.740` | `3.372` | `235.665` | `421.421` |
| `4194304` | `988/988` | `28.321` | `34.885` | `3.593` | `224.644` | `423.162` |

The `1kdocs` corpus averages about `108 KiB` per object, so chunk size is not the primary lever. The `4 MiB` run was best in this local sample, but keep this configurable and retest with larger-object corpora before changing production defaults.

## Metrics To Compare

The benchmark output includes:

| Metric | Meaning |
| --- | --- |
| `elapsed_seconds` | Total observed job runtime from DSX-Connect progress. |
| `items_per_second` | End-to-end terminal item throughput. |
| `reader_elapsed_ms` | Time to acquire readable content from the selected reader. |
| `stream_read_elapsed_ms` | Time spent reading the content stream while sending to DSXA. |
| `scanner_response_wait_elapsed_ms` | DSXA request time not spent reading the stream. |
| `scanner_engine_elapsed_ms` | Scanner engine time reported by DSXA. |
| `dsxa_elapsed_ms` | Wall time for the DSXA request. |
| `queue_wait_ms` | Time between accepted work and scan-stage activity when available. |

Interpretation:

* High `reader_elapsed_ms` usually points to connector setup, connector lookup, or proxy response delay.
* High `stream_read_elapsed_ms` usually points to repository read speed, connector proxy throughput, or network.
* High `scanner_response_wait_elapsed_ms` with low stream time usually points to scanner-side queueing or DSXA response latency.
* High `queue_wait_ms` usually points to relay, RabbitMQ, worker capacity, or active item caps.

## Recommended Comparison Table

Use this table shape when comparing with 1G:

| Label | Mode | Items | Elapsed sec | Items/sec | Failures | Reader avg/p95 ms | Stream avg/p95 ms | DSXA avg/p95 ms | Engine avg/p95 ms | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1G GCS batch | `1g-gcs-batch` | `1002` | `159` | `6.3` | `0` | | | | | historical local benchmark |
| 2G local GCS protected scope (stub scanner) | `2g-local-gcs-protected-scope-stub` | `1000` | `114.746` | `8.715` | `0` | | | | | Stub scanner isolates GCS read plus 2G workflow overhead. |

Paste the row emitted by `benchmark_ng_job.py` under the 1G row.

The stub-scanner row is not a DSXA or reader throughput measurement. The stub scanner does not open the object stream, so it is useful for isolating protected-scope enumeration, RabbitMQ dispatch, persistence, policy completion, and item finalization. In the July 14, 2026 local run, scan-stage latency averaged `77.865 ms` with `181.805 ms` p95, while queue wait averaged `57953.586 ms` with `95898.633 ms` p95. That points first at relay/queue/worker/policy workflow throughput rather than DSXA.

## Tune After Baseline

Take one baseline run before changing concurrency.
Then change one thing at a time:

| Knob | What it tests |
| --- | --- |
| scan worker replicas | Horizontal scan capacity. |
| `--prefetch-count` | RabbitMQ in-flight work per scan worker. |
| `--scan-batch-concurrency` | Read/scan coroutines inside scan-only worker batches. |
| policy worker `--prefetch-count` | Whether policy/finalization is serializing `scanned -> completed` transitions. For high-volume bucket scans, start at `100`. |
| relay active item cap | Whether scan workers are being starved by relay refill. |
| connector replicas | Whether connector proxy reads are the bottleneck. |
| reader strategy | Compare `proxy` with `native`. For GCS, native reads stream directly from GCS in the scan worker instead of routing content bytes through the connector. |
| DSXA scanner replicas/resources | Whether scanner capacity is the bottleneck. |

Keep each run tied to the exact values used so results remain explainable.
