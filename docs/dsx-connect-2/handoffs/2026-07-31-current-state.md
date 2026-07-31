# DSX-Connect 2 Current State Handoff - 2026-07-31

This handoff captures where DSX-Connect 2 stands after the July connector, UI, deployment, and benchmark work.

## Current Posture

DSX-Connect 2 is now a durable, operator-visible scanning workflow instead of a thin connector runner.

The working model is:

```text
Connectors own repository access and inventory.
DSX-Connect owns protected scopes, durable jobs, queues, policy, remediation, and reporting.
DSXA owns file analysis and verdicts.
```

Proxy readers remain the preferred default. They preserve the repository-agnostic core model by keeping repository credentials inside connectors. Native readers are supported as an advanced deployment-specific optimization, but current benchmarks do not justify making them the default.

## Important Repository State

Recent DSX-Connect 2 work includes:

- connector-driven asset type handling in the UI
- combined configured/inventory asset discovery
- simplified protected-asset filters
- table-level filters directly under matching column headers
- icon-only table actions with tooltips
- scan result polling and refresh indicators
- scan sample expansion from the job row
- scan statistics comparison with CSV export
- richer scan metadata sent to DSXA
- benchmark documentation and benchmark-results deck
- GKE WIF and non-GKE authentication guidance
- k3s filesystem connector deployment examples

The main benchmark tooling is:

```text
scripts/benchmark_ng_job.py
scripts/benchmark_gcs_readers.py
```

The current lab-oriented DSXA split manifest is:

```text
deploy/lab/dsxa-split-rest-config-k3s.yaml
```

That manifest is experimental. It records the intended one-config-pod plus multi-REST-pod topology, but it is not yet the recommended lab deployment path until the DSXA sync sidecar image is available.

## Lab Environments

### k3s Lab

The primary k3s lab is reachable through context:

```text
k3s-uslab
```

The node is:

```text
10.2.4.103
```

The VM was increased to:

```text
32 vCPU
32 GB memory
```

After the resize, k3s reported the node as Ready and the metrics server was usable again after firewall access was corrected.

The k3s lab stack has been used for the main GCS proxy-reader benchmark series. The scanner service was restored to the stable single-pod DSXA deployment after the experimental split topology test.

### GKE Lab

The GKE lab used for WIF and reader testing is:

```text
project: se-project-388112
cluster: gs-cluster
location: us-east4
context: gke_se-project-388112_us-east4_gs-cluster
```

The GCS connector has been validated with Workload Identity Federation for GKE. Native reader testing required temporarily allowing scan workers to use Google credentials. That is useful for benchmarking but should stay an explicit operator choice because it changes the credential boundary.

## DSXA Deployment Findings

Do not scale a single DSXA container running:

```text
FLAVOR=rest,config
```

That creates duplicate config/registration behavior for the same scanner identity and can cause registration or readiness instability.

The DSXA deployment guide describes the proper clustered shape:

```text
one config pod
multiple REST or ICAP classifier pods
load-balanced scanner service
sync sidecar for classifier pod configuration
```

The missing piece for the lab is the sync sidecar image. The guide references a private rsync image:

```text
us-docker.pkg.dev/di-dsx-external-artifacts/dsx-docker/rsync
```

If an equivalent image is published, for example:

```text
dsxconnect/rsync:4.2.0
```

then the lab can test a proper multi-REST DSXA deployment.

Until then, the stable k3s scanner posture is a single `dsxa-scanner` pod behind the `dsxa-scanner` service.

## Benchmark Summary

### DSX-Connect 1G Baseline

Historical GCS batch reference:

| System | Items | Runtime | Throughput |
| --- | ---: | ---: | ---: |
| DSX-Connect 1G GCS batch | `1002` | `159s` | `6.3 files/s` |

### k3s GCS Proxy Reader

Main k3s proxy-reader progression with `4468` GCS objects:

| Scan workers | Runtime | Throughput |
| ---: | ---: | ---: |
| `1` | `251.927s` | `17.735 files/s` |
| `2` | `177.632s` | `25.153 files/s` |
| `4` | `146.206s` | `30.560 files/s` |

After increasing the VM to `32 vCPU / 32 GB`, a clean single-job run produced:

| Job | Items | Runtime | Throughput | Failures |
| --- | ---: | ---: | ---: | ---: |
| `job_6250ffbc2a914949a6cc30a68a431b7d` | `4468` | `129.427s` | `34.521 files/s` | `0` |

That was about a `13%` improvement over the earlier `30.560 files/s` k3s proxy run.

### Concurrent Multi-Scan Test

Two full GCS scans were run concurrently against the stable single-DSXA k3s lab:

| Job | Items | Runtime | Throughput | Failures |
| --- | ---: | ---: | ---: | ---: |
| `job_65f6b6e092a3486883546457a38b85ec` | `4468` | `294.761s` | `15.158 files/s` | `0` |
| `job_69a15ff12f3e4b6297f589f1b424c2dd` | `4468` | `287.108s` | `15.562 files/s` | `0` |

Aggregate throughput was roughly:

```text
8936 files / 294.761s = 30.3 files/s
```

Concurrent scans did not improve total throughput in the current shape. They mostly split scan worker and scanner capacity between jobs.

### Proxy Versus Native Readers

k3s colocated connector/core test:

| Reader | Items | Throughput |
| --- | ---: | ---: |
| proxy | `4468` | `30.560 files/s` |
| native | `4468` | `31.448 files/s` |

GKE WIF test:

| Reader | Items | Throughput |
| --- | ---: | ---: |
| proxy | `500` | `15.281 files/s` |
| native | `500` | `14.068 files/s` |

The current evidence supports proxy as the default. Native readers may still be valuable when DSX-Connect runs inside the same cloud environment as the protected repository and benchmark data proves a material benefit.

## Architecture Conclusions

The strongest performance improvement over DSX-Connect 1G appears to come from batch workflow design:

```text
persist accepted batch
publish bounded work
scan with worker concurrency
track item state durably
complete policy/remediation/result stages from durable state
surface statistics for comparison
```

The reader path is not currently the dominant bottleneck. Queue wait, scan-worker concurrency, DSXA latency, RabbitMQ, PostgreSQL, and deployment sizing matter more in the observed lab runs.

That is good for the platform model because it means DSX-Connect can keep the core repo-agnostic while still delivering major throughput gains.

## Known Issues And Watch Items

- The DSXA multi-REST topology needs a real sync sidecar image before it can be benchmarked properly.
- The experimental split DSXA manifest should remain lab-only until validated.
- Multi-scan concurrency currently divides capacity rather than increasing aggregate throughput.
- Scan worker count above `4` has not been fully retested after the VM resize.
- RabbitMQ showed meaningful CPU during benchmark runs and should be watched during larger tests.
- DSXA scanner pod memory should be sized closer to deployment guidance for sustained benchmarking.
- Native reader credentials in scan workers should remain opt-in because they change the trust model.

## Useful Commands

Check k3s lab health:

```bash
kubectl --context k3s-uslab get nodes
kubectl --context k3s-uslab -n dsx-connect get pods -o wide
kubectl --context k3s-uslab -n dsx-connect top pods
kubectl --context k3s-uslab top node
```

Check DSXA service routing:

```bash
kubectl --context k3s-uslab -n dsx-connect get svc dsxa-scanner
kubectl --context k3s-uslab -n dsx-connect get endpoints dsxa-scanner -o wide
```

Run a protected-scope benchmark:

```bash
./.venv/bin/python scripts/benchmark_ng_job.py \
  --api-base-url https://dsx-connect.10.2.4.103.nip.io/api/v1 \
  --scope-id scope_ca7f4196027c4fb0a4e4d759cd571624 \
  --label "2G k3s GCS proxy reader benchmark" \
  --mode "2g-k3s-gcs-proxy-reader" \
  --reader-strategy proxy \
  --limit 10000 \
  --poll-interval-seconds 5 \
  --progress-item-limit 1000 \
  --sample-items-limit 100 \
  --insecure
```

## Suggested Next Steps

1. Publish or otherwise provide the DSXA rsync/sync sidecar image.
2. Convert the experimental split manifest into a validated k3s lab deployment.
3. Run single-scan and concurrent-scan benchmarks with multiple REST classifier pods.
4. Retest scan worker replicas above `4` on the resized k3s VM.
5. Capture resource usage alongside benchmark results.
6. Keep proxy reader as the default recommendation unless native proves a clear deployment-specific win.
