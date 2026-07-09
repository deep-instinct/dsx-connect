# DSX-Connect NG

`dsx_connect_ng` is a separate application boundary for the new DSX-Connect architecture.

It exists to implement the next-generation control plane and worker model without coupling new architecture decisions to the current `dsx_connect` runtime.

Package-local docs now live under [docs/index.md](docs/index.md).

## Goals

- keep next-generation implementation isolated from legacy `dsx_connect`
- make PostgreSQL and RabbitMQ first-class from the start
- build the new control plane before migrating connector behavior
- treat connectors as integration adapters, not policy engines

## Non-Goals

- no imports from `dsx_connect.*`
- no reuse of legacy database tables
- no preview-only routes under the legacy FastAPI app
- no connector callback-based read path as the target architecture

## Initial Scope

Phase 1:

- standalone FastAPI service
- configuration model
- health/status endpoints
- control-plane package boundaries
- RabbitMQ-oriented job topology notes

Phase 2:

- PostgreSQL control-plane schema and migrations
- integration and protected-scope CRUD
- no-overlap validation
- core-owned scope matcher

Current scaffold now includes:

- control-plane CRUD for `integrations`
- connector-instance registration and heartbeat lease tracking
- opt-in connector framework registration via `DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true`
- enrollment-token auth for NG connector registration via `DSX_CONNECT_NG__CONNECTOR_ENROLLMENT_TOKENS`
- deployment-native NG instance identity via `DSXCONNECTOR_INSTANCE_ID`
- control-plane CRUD for `protected_scopes`
- in-memory control-plane repository/service
- first SQL migration at `migrations/0001_control_plane.sql`
- canonical job persistence with in-memory and PostgreSQL repositories
- execution outbox schema in `migrations/0002_jobs.sql`
- explicit batch job item persistence in `migrations/0003_job_items.sql`
- runtime-agnostic stage message contracts in `dsx_connect_ng/jobs/contracts.py`

Phase 3:

- canonical domain jobs
- RabbitMQ publishers/consumers
- worker-hosted Readers
- pilot integration in shadow mode

## Separation Rules

Hard rules for this app:

1. `dsx_connect_ng` may depend on neutral packages such as `shared` or SDKs, but must not import `dsx_connect`.
2. API routes, settings, workers, and persistence are owned here, not shared with the legacy app.
3. PostgreSQL schema ownership is separate from legacy tables.
4. RabbitMQ is the durable transport boundary for job orchestration. Legacy DLQ handling should not be copied directly; dead-letter routing should be expressed through RabbitMQ exchanges/queues/policies.

## API Boundary

This implementation should keep three API families clearly separated:

- `control-plane APIs`: configuration, intent, and orchestration metadata
- `execution APIs`: scan-path and worker/backend execution contracts
- `UI APIs`: frontend-oriented APIs used by browser or desktop user interfaces

These are not the same surface and should not drift into a single undifferentiated router tree.

### Control-Plane API

Purpose:

- integration registration
- connector health and capability negotiation
- scope/job orchestration metadata
- policy attachment and protection model management

Characteristics:

- stable machine contract
- explicit versioning
- no frontend-shaped response assumptions
- optimized for automation and service-to-service use

Suggested namespace:

- `/api/v1/control-plane/...`

### Execution API

Purpose:

- scan submission
- fetch/read/scan/finalize contracts
- remediation execution contracts
- worker and broker coordination
- machine-oriented result handoff

Characteristics:

- this is the reliability boundary for the scan path
- stable machine contract
- no frontend-shaped convenience payloads
- stricter compatibility expectations than UI routes

Suggested namespace:

- `/api/v1/execution/...`

Job transport policy:

- `InMemoryJobBus` is a local development and test double
- it is not an "in-memory RabbitMQ"
- real broker semantics are only validated against RabbitMQ

### UI API

Purpose:

- frontend dashboard reads/writes
- operator workflows
- human-facing summaries and convenience views
- presentation-oriented aggregation

Characteristics:

- may compose multiple control-plane objects into UI-friendly responses
- should not become the integration contract for connectors/workers
- can evolve independently of backend transport contracts

Suggested namespace:

- `/api/v1/ui/...`

### Design Rule

If a contract exists primarily so a worker, connector, or backend service can do work, it belongs under `execution`, not `ui`.

## Run

```bash
cd dsx_connect_ng
pip install -e .
python -m uvicorn dsx_connect_ng.app:app --reload
```

Queue-driven worker entrypoints:

```bash
cd dsx_connect_ng
pip install -e ".[workers]"
dsx-connect-ng-relay --once
dsx-connect-ng-scan-worker
dsx-connect-ng-policy-worker
dsx-connect-ng-remediation-worker
dsx-connect-ng-result-sink-worker
dsx-connect-ng-delivery-worker
dsx-connect-ng-dianna-worker
dsx-connect-ng-local init
dsx-connect-ng-local foreground
dsx-connect-ng-local debug --service api --service scan-worker
dsx-connect-ng-local --with-rabbit-docker foreground
dsx-connect-ng-local --with-postgres-docker --with-rabbit-docker foreground
```

The scan, policy, remediation, delivery, and DIANNA workers currently run as queue-driven adapters/stubs:

- the scan worker consumes `scan.requested` and posts typed scan-stage callbacks
- the policy worker consumes `policy.requested` and posts typed policy-stage callbacks
- the remediation worker consumes `remediation.requested` and posts typed remediation-stage callbacks
- the result-sink worker currently exists as a transitional adapter:
  - it consumes `result_sink.emit.requested`
  - emits structured result events to the configured ResultSink
  - only `workflow_summary` deliveries advance `delivery_stage`
- `dsx-connect-ng-delivery-worker` remains as a compatibility alias during the rename
- in the local runtime manager, the service name is now `result-sink-worker`
- `delivery-worker` remains accepted as a legacy service selector alias
- the DIANNA worker consumes `dianna.requested` and posts typed dianna-stage callbacks
- both use the same `JobService` and execution contract as the API, so moving from in-process stubs to real consumers does not change the protocol shape
- `dsx-connect-ng-local foreground` starts the API, relay, scan worker, policy worker, remediation worker, result-sink worker, and DIANNA worker together for local testing
- `dsx-connect-ng-local debug --service ...` starts only the selected services and does not fail-fast when one child exits, which is more practical for debugger attach workflows
- `dsx-connect-ng-local --with-rabbit-docker foreground` will also start a local `rabbitmq:3-management` container if Docker is available and the named container is not already running
- `dsx-connect-ng-local --with-postgres-docker --with-rabbit-docker foreground` is the intended multi-process stub pipeline mode, because separate API/worker processes need shared PostgreSQL state
- for UI-only local preview, run the API with memory backends and seed demo data:

```bash
DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=memory \
DSX_CONNECT_NG__JOB_BUS_BACKEND=memory \
python -m uvicorn dsx_connect_ng.app:app --host 127.0.0.1 --port 8093

curl -X POST http://127.0.0.1:8093/api/v1/ui/demo/seed
```

- `/api/v1/ui/demo/seed` is UI-only and local-preview oriented; it is rejected outside `dev`, `local`, or `test` environments

Scan worker modes:

- `DSX_CONNECT_NG_SCANNER__MODE=stub|auto|dsxa`
- `stub` keeps the current synthetic scan behavior for local pipeline testing
- `dsxa` uses the real DSXA SDK path and requires:
  - `DSX_CONNECT_NG_SCANNER__BASE_URL`
  - optional `DSX_CONNECT_NG_SCANNER__DSXA_AUTH_TOKEN`
  - optional `DSX_CONNECT_NG_SCANNER__PROTECTED_ENTITY`
  - optional `DSX_CONNECT_NG_SCANNER__VERIFY_TLS`
- the current real scan path now goes through a worker-hosted reader abstraction
- reader strategy is resolved in this order:
  - per-request override from `scan_options.readerStrategy` / `reader_strategy`
  - per-request override from `read_hint.readerStrategy` / `reader_strategy`
  - integration config, for example `config.reader.default_strategy`
  - `DSX_CONNECT_NG_READERS__DEFAULT_STRATEGY`
- supported strategies today are:
  - `native`
  - `proxy`
  - `cached`
  - `quarantine`
- `native`, `cached`, and `quarantine` currently resolve to the local-path reader implementation
- `proxy` now uses a `ConnectorProxyReader` that calls a connector-compatible `read_file` endpoint and stages the response to a local temp file for DSXA scanning
- result sink backends currently supported are:
  - `stdout`
  - `json_lines`
- local/dev default is:
  - `DSX_CONNECT_NG_RESULT_SINK__BACKEND=stdout`
  - so stage result events are easy to inspect directly in worker output
- if you prefer collector-friendly file output, set for example:

```bash
DSX_CONNECT_NG_RESULT_SINK__BACKEND=json_lines
DSX_CONNECT_NG_RESULT_SINK__PATH=/tmp/dsx-connect-ng-results.jsonl
```

- that JSON-lines file can then be tailed by rsyslog, Vector, Fluent Bit, or similar tooling
- proxy reader configuration currently comes from integration `config.reader.proxy`, for example:

```json
{
  "reader": {
    "default_strategy": "proxy",
    "proxy": {
      "base_url": "http://127.0.0.1:8620",
      "connector_name": "filesystem",
      "auth_mode": "none"
    }
  }
}
```

That integration config is now parsed as a typed runtime model with this logical shape:

- `config.reader.default_strategy`
- `config.reader.proxy.endpoint_url`
- `config.reader.proxy.base_url`
- `config.reader.proxy.connector_name`
- `config.reader.proxy.auth_mode`
- `config.reader.proxy.header_name`
- `config.reader.proxy.header_value`
- `config.reader.proxy.hmac_key_id`
- `config.reader.proxy.hmac_secret`
- `config.reader.proxy.timeout_seconds`

- proxy reader auth modes currently supported are:
  - `none`
  - `static_header`
  - `dsx_hmac`
- proxy reader currently bridges to the first-generation connector `read_file` request shape:
  - `location`
  - `metainfo`
  - optional `size_in_bytes`
  - `scan_job_id`
- local filesystem example:
  - run connector on `http://127.0.0.1:8620`
  - create integration with:

```json
{
  "integration_id": "filesystem-local",
  "platform": "filesystem",
  "platform_key": "local-filesystem",
  "display_name": "Filesystem Local",
  "capability_read": true,
  "config": {
    "reader": {
      "default_strategy": "proxy",
      "proxy": {
        "base_url": "http://127.0.0.1:8620",
        "connector_name": "filesystem-connector",
        "auth_mode": "none"
      }
    }
  }
}
```

Filesystem proxy-reader validation helper:

```bash
python3 scripts/validate_ng_proxy_reader.py --poll
```

That helper will:

- create `~/.dsx-connect-local/filesystem-connector/data/scan/proxy-reader-sample.txt`
- create or update integration `filesystem-local`
- submit a one-item batch with `readerStrategy=proxy`
- include a stub `policyDecision.delivery_target` so the default local worker chain can reach a terminal delivery state
- optionally poll the first job item until terminal state and print:
  - scan stage
  - policy stage
  - remediation stage
- delivery stage
- dianna stage
- current item state at each poll interval

If you want to validate the narrower end-to-end scan slice only:

- proxy read
- real DSXA scan
- `scan_result` emission
- no workflow summary emission

run:

```bash
python3 scripts/validate_ng_proxy_reader.py --scan-only --poll
```

In that mode the item should still reach terminal state, with:

- `delivery_stage.state = "skipped"`
- `delivery_stage.result.reason = "workflow_summary_not_requested"`
- emitted `scan_result` events now carry top-level convenience fields such as:
  - `schema_version`
  - `verdict`
  - `file_type`
  - `scan_guid`
  - `file_hash`
  - `content_source_mode`
  - `scanner_metadata`
  - non-summary events do not include `workflow_summary`

If you want to exercise a likely-malicious scan path with the standard EICAR test string, run:

```bash
python3 scripts/validate_ng_proxy_reader.py --scan-only --sample-kind eicar --poll
```

That path is still subject to your DSXA environment actually classifying EICAR as malicious, but it is the intended real-path validation input.

If you want to validate batch expansion from one submitted batch into multiple `job_item` records, run:

```bash
python3 scripts/validate_ng_batch_proxy_reader.py --scan-only --poll
```

That helper will:

- create multiple sample files
- submit one batch request with multiple items
- poll until all expanded `job_item`s reach terminal state
- print the parent `item_summary`, `job_item_ids`, and per-item terminal states

If local runtime is configured with the `json_lines` result sink backend, the batch helper can also validate the emitted result-sink payloads for the specific batch job:

```bash
python3 scripts/validate_ng_batch_proxy_reader.py --scan-only --sample-kind eicar --item-count 6 --poll --result-sink-path /tmp/dsx-connect-ng-results.jsonl
```

In `--scan-only` mode this asserts:

- one `scan_result` event per submitted item
- no `workflow_summary` events
- each event includes:
  - `schema_version = "1.0"`
  - `verdict`
  - `scan_guid`
  - `content_source_mode`

For the full workflow-summary path, keep `--scan-only` off and the helper will additionally require one `workflow_summary` event per submitted item:

```bash
python3 scripts/validate_ng_batch_proxy_reader.py --sample-kind eicar --item-count 3 --poll --result-sink-path /tmp/dsx-connect-ng-results.jsonl
```

If you want to validate intentional parallel scan execution rather than single-file progression, start the local stack with a higher scan-worker prefetch count and require overlap during the batch run:

```bash
dsx-connect-ng-local --with-postgres-docker --with-rabbit-docker --scan-worker-prefetch-count 2 foreground
python3 scripts/validate_ng_batch_proxy_reader.py --scan-only --sample-kind eicar --item-count 6 --poll --min-concurrent-scans 2
```

That flow asserts that at least two batch items were observed in `scan_stage.state = "running"` at the same time. If you want to cap concurrency during validation, the helper also accepts `--max-concurrent-scans`.

For a real connector-proxy read-path validation, run the scan worker in DSXA mode so the scan executor actually invokes the selected Reader:

```bash
export DSX_CONNECT_NG_SCANNER__MODE=dsxa
export DSX_CONNECT_NG_SCANNER__BASE_URL=http://127.0.0.1:15000
```

If scan worker remains in `stub` mode, the batch still validates integration config and orchestration, but it will not exercise the real proxy read transport.

Google Cloud Storage proxy-reader example:

```json
{
  "integration_id": "gcs-local",
  "platform": "google-cloud-storage",
  "platform_key": "bucket-1",
  "display_name": "GCS Local",
  "capability_read": true,
  "config": {
    "reader": {
      "default_strategy": "proxy",
      "proxy": {
        "base_url": "http://127.0.0.1:8595",
        "connector_name": "google-cloud-storage-connector",
        "auth_mode": "none",
        "timeout_seconds": 30
      }
    }
  }
}
```

That gives GCS the same contract shape as filesystem:

- scan worker stays generic
- `proxy` strategy still bridges through the connector `read_file` capability
- later, DI can add a native GCS reader without changing the scan-stage contract
- the concrete local-path resolution logic expects a readable local file path from either:
  - `content_source.locator`
  - scan options such as `path`, `file_path`, `filePath`, `local_path`, `localPath`, or `selector`
  - or `object_identity` if it is itself a readable local file path

Example endpoints:

- `GET /api/v1/control-plane/status`
- `GET /api/v1/control-plane/integrations`
- `POST /api/v1/control-plane/integrations`
- `GET /api/v1/control-plane/scopes`
- `POST /api/v1/control-plane/scopes`
- `GET /api/v1/control-plane/scope-match?integration_id=...&scope_type=path&resource_selector=/finance/report.pdf`
- `GET /api/v1/execution/status`
- `GET /api/v1/execution/topology`
- `POST /api/v1/execution/jobs`
- `POST /api/v1/execution/jobs/batch`
- `GET /api/v1/execution/jobs`
- `GET /api/v1/execution/jobs/{job_id}`
- `GET /api/v1/execution/jobs/{job_id}/batch`
- `GET /api/v1/execution/jobs/{job_id}/items`
- `GET /api/v1/execution/job-items/{job_item_id}`
- `POST /api/v1/execution/job-items/{job_item_id}/scan-stage`
- `POST /api/v1/execution/job-items/{job_item_id}/policy-stage`
- `POST /api/v1/execution/job-items/{job_item_id}/remediation-stage`
- `POST /api/v1/execution/job-items/{job_item_id}/remediation-request`
- `POST /api/v1/execution/job-items/{job_item_id}/delivery-stage`
- `POST /api/v1/execution/job-items/{job_item_id}/result-sink-request`
- `POST /api/v1/execution/job-items/{job_item_id}/dianna-request`
- `POST /api/v1/execution/job-items/{job_item_id}/dianna-stage`
- `GET /api/v1/execution/outbox`
- `GET /api/v1/execution/outbox/{outbox_id}`
- `POST /api/v1/execution/outbox/flush`

PostgreSQL settings:

- `DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=auto|memory|postgres`
- `DSX_CONNECT_NG_POSTGRES__URL=postgresql://...`
- `DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA=true`

Backend behavior:

- `memory`: always use the in-memory repository
- `postgres`: require PostgreSQL and fail if unavailable
- `auto`: try PostgreSQL and fall back to memory for local development

If PostgreSQL is unavailable, `auto` falls back to the in-memory repository so development can continue.

Execution persistence behavior:

- canonical jobs follow the control-plane storage backend
- if control-plane storage is `memory`, jobs are stored in-memory
- if control-plane storage is `postgres`, jobs and outbox records are stored in PostgreSQL
- execution publish still goes through the configured job bus after the canonical job is recorded

Job bus settings:

- `DSX_CONNECT_NG__JOB_BUS_BACKEND=memory|rabbitmq|auto`
- `DSX_CONNECT_NG_RELAY__BATCH_SIZE=100`
- `DSX_CONNECT_NG_RELAY__POLL_INTERVAL_SECONDS=5.0`

Job bus behavior:

- `memory`: always use the in-process test bus
- `rabbitmq`: require RabbitMQ transport implementation
- `auto`: try RabbitMQ bus wiring and fall back to memory only if bootstrap fails

Execution submit behavior:

- `POST /api/v1/execution/jobs` creates a canonical job record first
- `POST /api/v1/execution/jobs/batch` creates a parent job plus explicit child item records
- an outbox record is written before publish is attempted
- successful publish moves the job to `queued`
- failed publish moves the job to `publish_pending`
- `idempotency_key` is honored when provided
- pending outbox records can be inspected and retried through the execution API

Transaction Outbox Pattern:

- this execution model follows the Transaction Outbox Pattern
- PostgreSQL stores the canonical state change and the durable intent to publish
- RabbitMQ stores and redelivers the message after publish succeeds
- RabbitMQ durability alone is not sufficient for producer-side correctness, because the process may commit PostgreSQL state and crash before the broker receives the message
- for that reason, the outbox is the producer-side durability boundary and RabbitMQ is the transport boundary
- outbox publish ownership is claimed atomically before publish so immediate publish and relay retry cannot publish the same outbox record concurrently

Batch job behavior:

- parent job state is separate from per-item state
- each file/object in a batch is stored as a `job_item`
- each item carries a `content_source` describing where later stages can obtain bytes
- each item carries `delivery_requirements` so final delivery can wait on optional branches such as DIANNA when policy requires it
- outbox publish is per item, not only per parent batch
- current batch submission publishes `scan_item_requested` messages onto the transport
- `GET /api/v1/execution/jobs/{job_id}/batch` returns the parent job plus aggregate item counts
- `GET /api/v1/execution/jobs/{job_id}/items` returns the per-item records

Worker callback behavior:

- workers consume item-level queue messages, not only parent batch IDs
- scan, remediation, delivery, and DIANNA each have their own stage record on the item
- policy is now an explicit stage between scan and remediation/delivery branching
- workers report only their own stage outcome, not the whole item/business lifecycle
- `POST /api/v1/execution/job-items/{job_item_id}/scan-stage` accepts a typed scan result payload
- `POST /api/v1/execution/job-items/{job_item_id}/policy-stage` accepts a typed policy decision payload and drives post-scan branching
- `POST /api/v1/execution/job-items/{job_item_id}/remediation-stage` accepts a typed remediation result payload
- `POST /api/v1/execution/job-items/{job_item_id}/remediation-request` publishes a typed remediation work request
- `POST /api/v1/execution/job-items/{job_item_id}/delivery-stage` accepts a typed delivery result payload
- `POST /api/v1/execution/job-items/{job_item_id}/result-sink-request` publishes the outward-facing workflow summary payload to the configured ResultSink
- `POST /api/v1/execution/job-items/{job_item_id}/dianna-stage` accepts a typed DIANNA result payload
- parent batch state is recomputed from child stage state plus any pending publish state
- scan-stage completion publishes `policy_evaluation_requested`
- policy-stage completion can automatically publish `remediation_requested`
- policy-stage completion can automatically publish `dianna_analysis_requested`
- policy-stage completion can automatically publish `result_sink_emit_requested` for the common no-remediation path
- remediation-stage completion or skip can automatically publish `result_sink_emit_requested`
- DIANNA-stage terminal updates can automatically publish `result_sink_emit_requested` when delivery is configured to wait for DIANNA

Stage model:

- `scan_stage`: read/fetch and DSXA scan execution
- `policy_stage`: post-scan policy decision and orchestration outputs
- `remediation_stage`: policy/remediation execution
- `delivery_stage`: posting/publishing final results outward
- `dianna_stage`: optional DIANNA enrichment branch
- each stage carries `state`, `started_at`, `completed_at`, `result`, and `error`

Content source model:

- `content_source` is the item-level reference for where bytes can still be obtained
- current modes are `original`, `quarantine`, `cached`, and `none`
- DIANNA requests depend on `content_source` rather than assuming the original path is still valid
- policy/remediation can later update `content_source` if the file is moved, quarantined, cached, or deleted

Delivery gating model:

- `delivery_requirements.wait_for_dianna=true` means outward delivery must wait until `dianna_stage` reaches a terminal state
- DIANNA request can opt into that mode when automated malicious-file analysis is required
- delivery payloads combine the current `scan`, `remediation`, `dianna`, and `contentSource` data into one machine-oriented result document

Message contracts:

- `scan_item_requested`
- `scan_item_completed`
- `scan_item_failed`
- `policy_evaluation_requested`
- `policy_evaluation_completed`
- `policy_evaluation_failed`
- `remediation_requested`
- `remediation_completed`
- `remediation_failed`
- `dianna_analysis_requested`
- `dianna_analysis_completed`
- `dianna_analysis_failed`
- `result_sink_emit_requested`
- `result_sink_emit_completed`
- `result_sink_emit_failed`
- legacy aliases still parse:
  - `result_delivery_requested`
  - `result_delivery_completed`
  - `result_delivery_failed`

Typed message payloads:

- queue message models in `dsx_connect_ng/jobs/contracts.py` now use typed bodies for scan results, policy decisions, remediation plans/results, DIANNA results, and delivery results
- worker stubs can parse `MessageEnvelope` into typed request models with `from_envelope()` helpers instead of manually unpacking dict payloads

Worker stubs:

- `dsx_connect_ng/workers/scan_worker.py` is a minimal in-process scan worker stub
- `dsx_connect_ng/workers/policy_worker.py` is a minimal in-process policy worker stub
- both operate on typed queue messages and drive the execution API/service through typed stage callbacks

These are modeled in `dsx_connect_ng/jobs/contracts.py` and are intended to remain valid whether the eventual consumers are plain RabbitMQ consumers or Celery workers.

RabbitMQ stage topology:

- `scan` queue family
  - strongest retry/DLQ posture
  - failures here matter most because missed scans are the main risk
- `dianna` queue family
  - optional malicious-only/manual analysis branch
  - bounded retry without re-scan
- `remediation` queue family
  - bounded retry
  - failures do not imply re-scan
- `result_sink` queue family
  - bounded retry
  - failures do not imply re-scan or re-remediation

RabbitMQ retry/DLQ behavior:

- retryable worker failures are republished to the queue family `*.retry` queue
- retry queues use TTL and dead-letter back to the primary work queue
- non-retryable worker failures are published directly to the queue family `*.dlq` queue
- exhausted retries are also published to the queue family `*.dlq` queue
- retry attempt count is tracked in the message header:
  - `x-dsx-retry-attempt`
- current runtime knobs:
  - `DSX_CONNECT_NG_RABBITMQ__RETRY_MAX_ATTEMPTS`
  - `DSX_CONNECT_NG_RABBITMQ__RETRY_DELAY_MS`
- `GET /api/v1/execution/topology` exposes configured queue families, retry queues, DLQs, routing keys, and retry runtime
- `GET /api/v1/execution/topology` is intentionally a configured-topology view only:
  - it does not inspect live queue depth
  - it does not expose broker message contents
  - it does not provide replay controls

Current stage-level retry semantics:

- terminal failures should be handled in-worker and persisted as terminal stage errors
- retryable failures should be raised so RabbitMQ retry / DLQ policy can own the retry path
- the scan worker now follows this split explicitly

DLQ replay:

- manual replay/restart of DLQ items is not implemented yet
- the intended next step is to expose DLQ visibility first and replay second, rather than requiring operators to interact with RabbitMQ directly

The current topology summary lives in `dsx_connect_ng/jobs/topology.py`.

DIANNA behavior:

- DIANNA is not part of the mandatory completion path
- DIANNA can be requested manually with `POST /api/v1/execution/job-items/{job_item_id}/dianna-request`
- the current guard only allows DIANNA after a completed malicious or suspicious scan result
- the current guard also requires an available `content_source`
- DIANNA failure does not imply re-scan
- a future automated mode can choose to delay final result delivery until DIANNA completes, if policy requires DIANNA-enriched delivery

Relay worker:

- `dsx-connect-ng-relay --once` flushes pending outbox records once and exits
- `dsx-connect-ng-relay` runs a simple polling relay loop
- the relay worker is responsible only for `outbox -> job bus` retry, not scanning or file reads

## Tests

Run the local test slice with:

```bash
python3 -m pytest dsx_connect_ng/tests -q
```

Example relay commands:

```bash
cd dsx_connect_ng
pip install -e ".[workers]"
dsx-connect-ng-relay --once
```

Continuous relay loop:

```bash
dsx-connect-ng-relay --batch-size 100 --poll-interval-seconds 5
```

Optional PostgreSQL repository tests:

- set `DSX_CONNECT_NG_TEST_POSTGRES_URL=postgresql://...`
- those tests are skipped automatically when the env var is absent

## Why Not Redis

Redis is intentionally not treated as a primary control-plane backend.

For DSX-Connect NG:

- `memory` is the local developer convenience backend
- `postgres` is the only durable control-plane backend
- `rabbitmq` is the transport/redelivery layer

Redis may still make sense later for cache or ephemeral coordination, but not as the source of truth for:

- integrations
- protected scopes
- canonical jobs
- overlap invariants
- idempotency

## Package Layout

- `dsx_connect_ng/api`: FastAPI routes
- `dsx_connect_ng/api/routes/control_plane.py`: machine-oriented API family
- `dsx_connect_ng/api/routes/execution.py`: scan-path execution API family
- `dsx_connect_ng/api/routes/ui.py`: frontend-oriented API family
- `dsx_connect_ng/config.py`: settings and feature gates
- `dsx_connect_ng/control_plane`: control-plane domain and repositories
- `dsx_connect_ng/jobs`: canonical domain-job models and queue topology
- `dsx_connect_ng/integrations`: integration contracts and capability declarations
- `dsx_connect_ng/readers`: worker-side reader abstractions
- `dsx_connect_ng/workers`: worker runtime entrypoints and orchestration

## Notes

See:

- [docs/architecture-vnext/design/architecture-overview.md](../docs/architecture-vnext/design/architecture-overview.md)
- [docs/architecture-vnext/rfc/control-plane-schema-rfc.md](../docs/architecture-vnext/rfc/control-plane-schema-rfc.md)
- [docs/architecture-vnext/rfc/job-model-rfc.md](../docs/architecture-vnext/rfc/job-model-rfc.md)
- [docs/architecture-vnext/rfc/scope-engine-rfc.md](../docs/architecture-vnext/rfc/scope-engine-rfc.md)
- [bootstrap-plan.md](bootstrap-plan.md)
