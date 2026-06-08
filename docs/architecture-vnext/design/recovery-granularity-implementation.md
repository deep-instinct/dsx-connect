# Recovery Granularity Implementation Guide

This document turns [ADR-013](../adr/adr-013-tunable-recovery-granularity-and-transaction-outbox.md) into concrete implementation work for `dsx_connect_ng`.

It assumes the existing v2 execution model remains in place:

- PostgreSQL is the canonical execution ledger
- RabbitMQ is the asynchronous transport
- asynchronous stage handoff uses the Transaction Outbox Pattern
- workers and downstream side effects must remain idempotent

## Goal

Add tunable full-scan recovery granularity without weakening durable orchestration.

The system should always persist:

- accepted work
- current execution state
- durable intent to publish

The system should make configurable:

- how precisely interrupted work resumes

## Recovery Modes

The implementation should support four modes:

### `item`

- resume incomplete items only
- highest resume precision
- highest persistence and orchestration precision

### `batch`

- resume from the last incomplete accepted batch
- replay incomplete items in that batch
- intended default for many small-file workloads

### `shard`

- resume from a persisted shard / cursor / partition boundary
- intended for very large enumerations

### `adaptive`

- resolve to `item`, `batch`, or `shard` at acceptance time
- persist the effective resolved mode on the job

## Design Rule

Do not recompute recovery mode on restart.

At acceptance time the system may evaluate policy dynamically, but after that the resolved effective mode becomes part of the persisted execution state for that unit of work.

## 1. Config Surface

Primary modules:

- [dsx_connect_ng/dsx_connect_ng/config.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/config.py:1)
- [dsx_connect_ng/dsx_connect_ng/control_plane/config_models.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/control_plane/config_models.py:1)

Add execution recovery settings with explicit defaults.

Suggested model:

```python
RecoveryMode = Literal["item", "batch", "shard", "adaptive"]

class RecoverySettings(BaseModel):
    mode: RecoveryMode = "batch"
    batch_size: int = 100
    checkpoint_every_items: int | None = None
    checkpoint_every_seconds: int | None = None
    large_object_threshold_bytes: int | None = None
    prefer_item_mode_for_archives: bool = True
```

Recommended config attachment points:

- global service default in `config.py`
- integration or scope-level execution policy in control-plane config models
- optional per-job override in execution submit payload

Implementation requirement:

- policy resolution must produce one persisted `effective_recovery_mode`
- policy origin should be explainable for debugging

## 2. Job / Batch Data Model

Primary module:

- [dsx_connect_ng/dsx_connect_ng/jobs/models.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/models.py:1)

Add execution metadata to parent job / batch models.

Recommended additions:

- `recovery_mode_requested`
- `effective_recovery_mode`
- `recovery_policy_snapshot`
- `recovery_checkpoint`

The checkpoint structure should be mode-aware.

Suggested shape:

```python
class RecoveryCheckpoint(BaseModel):
    mode: RecoveryMode
    batch_id: str | None = None
    last_completed_item_index: int | None = None
    shard_id: str | None = None
    cursor: str | None = None
    last_checkpoint_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)
```

Design note:

- `item` mode may not need much beyond current item stage records
- `batch` and `shard` benefit from an explicit persisted recovery boundary

## 3. Batch / Shard Persistence

Primary modules:

- [dsx_connect_ng/dsx_connect_ng/jobs/repository.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/repository.py:1)
- [dsx_connect_ng/dsx_connect_ng/jobs/postgres_repo.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/postgres_repo.py:1)

Extend repository APIs so recovery metadata is first-class rather than hidden in opaque payload JSON.

Recommended repository capabilities:

- update effective recovery mode
- update recovery checkpoint
- list incomplete batches
- list incomplete shards
- load replay candidates for a batch or shard

For PostgreSQL-backed execution, prefer explicit columns or explicit JSON structures over ad hoc nested payload mutation.

Suggested first step:

- keep checkpoint state in structured JSON if needed for speed of implementation
- reserve the option to normalize shard/cursor checkpoints into their own table once semantics stabilize

## 4. Execution API Surface

Primary module:

- [dsx_connect_ng/dsx_connect_ng/api/routes/execution.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/api/routes/execution.py:1)

Expose recovery metadata through the execution API so operators and tests can inspect effective behavior.

Recommended additions:

- include `effective_recovery_mode` in batch/job responses
- include `recovery_checkpoint` in batch/job responses
- later, add recovery-oriented read endpoints if shard/cursor state becomes separate

Non-goal for first implementation:

- do not expose pause/resume controls here unless restart semantics are already defined and tested

## 5. Recovery Resolution Logic

Primary module:

- [dsx_connect_ng/dsx_connect_ng/jobs/service.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/service.py:1)

Add one explicit recovery policy resolver in `JobService` or a helper it owns.

Responsibilities:

- resolve requested mode against policy
- infer adaptive mode from workload hints
- persist `effective_recovery_mode` at job acceptance time

Potential adaptive inputs:

- estimated object size
- archive/container hint
- integration policy
- explicit override

Design rule:

- adaptive resolution must happen once per batch/shard acceptance boundary
- the result is persisted and used unchanged during restart

## 6. Recovery Planner

Primary module:

- [dsx_connect_ng/dsx_connect_ng/jobs/service.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/service.py:1)

Create one recovery planner path that turns persisted state into replay work.

Suggested interface:

```python
plan = service.plan_recovery(job_id)
```

Planner outputs should answer:

- what mode is active?
- what is the current recovery boundary?
- what units need replay?
- what work is already terminal and must not be replayed?

Mode-specific behavior:

### `item`

- replay incomplete items only

### `batch`

- find last incomplete accepted batch
- replay non-terminal items in that batch

### `shard`

- find last incomplete shard
- resume from persisted cursor or shard state

### `adaptive`

- use the already persisted effective mode

## 7. Outbox and Idempotency Expectations

Primary modules:

- [dsx_connect_ng/dsx_connect_ng/jobs/service.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/service.py:1)
- [dsx_connect_ng/dsx_connect_ng/jobs/repository.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/repository.py:1)
- [dsx_connect_ng/dsx_connect_ng/jobs/postgres_repo.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/jobs/postgres_repo.py:1)

This design assumes:

- Transactional Outbox on the producer side
- Idempotent Consumer behavior on the consumer side

Meaning:

- new replay work should always be emitted via the outbox
- duplicate delivery must still be tolerated by stage consumers
- recovery modes affect replay boundaries, not reliability semantics

Idempotency boundaries should be made explicit for:

- scan stage completion
- policy stage completion
- remediation requests and results
- result-sink emission

Especially important:

- `result_sink` should consider whether `job_item_id + result_type` is a natural dedupe key

## 8. Restart Flow

The intended restart flow should be:

1. load incomplete jobs/batches from PostgreSQL
2. read persisted `effective_recovery_mode`
3. read persisted `recovery_checkpoint`
4. compute replay units
5. emit replay work through outbox
6. continue normal RabbitMQ-driven execution

Design rule:

- restart should never bypass canonical state or outbox rules

## 9. Testing Plan

Relevant current test locations:

- `dsx_connect_ng/tests/test_job_service.py`
- `dsx_connect_ng/tests/test_job_repository.py`
- `dsx_connect_ng/tests/test_job_postgres_repo.py`
- `dsx_connect_ng/tests/test_local_runtime.py`

Add tests for:

### Resolution

- global default mode is applied
- integration policy overrides default
- adaptive mode resolves to expected effective mode

### Persistence

- effective mode is stored on accepted job/batch
- checkpoint updates are persisted and reload correctly

### Restart Semantics

- `item` mode replays incomplete items only
- `batch` mode replays last incomplete batch
- `shard` mode resumes last incomplete shard/cursor
- `adaptive` restart uses persisted effective mode, not re-evaluation

### Idempotency

- duplicate replay does not produce duplicate downstream state transitions
- result-sink duplicate handling is either prevented or explicitly deduped

## 10. Suggested Rollout Order

1. Add config and persisted `effective_recovery_mode`
2. Implement `batch` mode explicitly as the first tunable recovery boundary
3. Add restart planner for `batch`
4. Add `item` mode policy and tests
5. Introduce `adaptive` resolution
6. Add `shard` mode only when cursor/shard modeling is needed by a real connector workload

Reason:

- `batch` delivers most of the practical value quickly
- `item` is partly already supported by current per-item state
- `shard` introduces the most new modeling and should be justified by a real enumeration case

## Recommended Defaults

Initial operational defaults:

- default mode: `batch`
- default batch size: `100`
- prefer `item` for archive-heavy or explicitly large-object workloads

This matches observed 1g behavior:

- batching removes major handoff overhead
- Reader-native optimization should attack the hot path
- coarse replay is acceptable for many small-file scans
- fine replay is needed for long-running large-object scans

## Summary

The implementation should preserve one core separation:

- durability of accepted work is mandatory
- precision of restart boundary is tunable

That allows `dsx_connect_ng` to remain correctness-first while still making performance-sensitive workloads cheaper to operate.
