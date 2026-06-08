# ADR-013: Tunable Recovery Granularity and Transaction Outbox for Full-Scan Execution

- **Status:** Proposed
- **Date:** 2026-05-26
- **Decision Owners:** DSX-Connect Architecture
- **Related:** ADR-003 (Enumeration and Jobs), ADR-007 (Reader Contract), ADR-011 (ResultSink), ADR-012 (Scan Dispatch Gating)

## Context

`dsx_connect_ng` is adopting a durability-first execution model:

- PostgreSQL is the canonical source of truth for execution state
- RabbitMQ is the asynchronous transport boundary
- worker-hosted Readers are the long-term hot-path optimization for repository reads

This model improves recoverability and auditability, but it raises an important design question:

How precise must restart behavior be for large full scans?

Different workloads have very different replay costs:

- billions of small files may tolerate replay of part of the last accepted batch
- thousands of very large archives may require much finer restart precision
- massive enumerations may be better resumed at a shard or cursor boundary than a single object boundary

At the same time, the architecture must prevent producer-side message loss between durable state changes and RabbitMQ publish.

RabbitMQ durability alone is not sufficient for that requirement. Durable queues and persistent messages only protect messages after the broker has received them. They do not solve the producer-side dual-write problem:

1. application state is committed in PostgreSQL
2. process crashes before publishing the corresponding RabbitMQ message

The system therefore needs both:

- a reliable producer-side persistence pattern for message intent
- a configurable policy for how precisely interrupted full scans should resume

## Decision

DSX-Connect will use the **Transaction Outbox Pattern** for asynchronous execution handoff, and it will make full-scan recovery precision **policy-driven and tunable**.

### Transaction Outbox

For asynchronous stage transitions:

1. execution state and publish intent are written durably to PostgreSQL first
2. the outbox record is then published to RabbitMQ
3. outbox publish ownership must be claimed atomically before publish
4. failed publish attempts return the outbox record to retryable pending state

RabbitMQ remains the transport and redelivery mechanism.
PostgreSQL remains the source of truth for:

- execution state
- auditability
- idempotency
- producer-side publish intent

### Tunable Recovery Granularity

Recovery precision for full scans will not be fixed globally.

Instead, the system will support these recovery modes:

1. `item`
   - resume from the last incomplete item
2. `batch`
   - resume from the last incomplete accepted batch
3. `shard`
   - resume from the last incomplete shard/cursor/partition
4. `adaptive`
   - choose a mode using workload hints and policy thresholds

## Decision Drivers

- preserve durable intent and avoid producer-side message loss
- keep RabbitMQ as the execution transport without making it the sole source of truth
- avoid overpaying persistence overhead where replay cost is low
- support high-cost replay scenarios such as multi-GB archive scanning
- allow Reader-native hot-path gains to outweigh unnecessary orchestration granularity
- keep restart semantics explicit and operator-understandable

## Clarifying Principle

Durable acceptance and exact restart precision are not the same requirement.

The architecture must always answer:

- was work accepted?
- what work is still incomplete?

It does not always need to answer:

- what is the exact next single object index after restart?

If replaying a bounded amount of work is cheap, coarser checkpoints are acceptable.
If replaying a bounded amount of work is expensive, checkpoints should be finer.

## Why RabbitMQ Durability Alone Is Not Enough

RabbitMQ provides durable queues, persistent messages, acknowledgements, and redelivery.

Those guarantees begin only after the broker has accepted the message.

They do not protect against:

- PostgreSQL state committed but publish never attempted
- PostgreSQL state committed but process crashes before publish
- multiple producers racing to publish the same still-pending intent

The Transaction Outbox Pattern addresses exactly that producer-side reliability gap.

## Recovery Modes

### `item`

Use when replay cost is high.

Examples:

- very large archives
- very long DSXA scan times
- expensive remediation side effects
- customer requirement for minimal replay

Behavior:

- persist per-item stage progress as the effective recovery boundary
- restart from incomplete items only

### `batch`

Use when replay cost is low and throughput matters most.

Examples:

- large corpora of small files
- cheap rescans
- workloads where replaying some files is operationally acceptable

Behavior:

- persist accepted batch and item membership durably
- restart from the last incomplete batch
- replay remaining items in that batch if needed

### `shard`

Use when enumeration and partitioning dominate.

Examples:

- extremely large repositories
- cursor-based or partitioned enumeration
- workloads where exact per-item restart is less important than resuming the last partition

Behavior:

- persist shard/cursor state durably
- restart from the last incomplete shard

### `adaptive`

Use when one global mode is too blunt.

Possible inputs:

- object size
- object type / archive hint
- expected or historical scan duration
- integration-specific policy
- operator override

Indicative behavior:

- prefer `item` for large, slow, or archive-like objects
- prefer `batch` for small, cheap-to-replay files
- prefer `shard` for enumeration-dominated scans

## Policy Model

Suggested execution policy shape:

```json
{
  "execution": {
    "recovery": {
      "mode": "adaptive",
      "batch_size": 100,
      "checkpoint_every_items": 25,
      "checkpoint_every_seconds": 30,
      "large_object_threshold_bytes": 1073741824,
      "prefer_item_mode_for_archives": true
    }
  }
}
```

Policy attachment may exist at:

- global default
- integration
- protected scope
- per-job override where appropriate

## Crash / Restart Semantics

In all modes:

- accepted work must be durably represented in PostgreSQL
- outbox-driven publish intent must be durable before broker handoff
- RabbitMQ remains the asynchronous execution transport

On restart:

- `item` resumes incomplete items
- `batch` resumes incomplete batches
- `shard` resumes incomplete shards
- `adaptive` resumes according to the persisted effective mode for that unit of work

## Data Model Implications

Recommended additions or explicit modeling:

- effective recovery mode on parent batch/job
- batch checkpoint state
- optional shard/cursor checkpoint records
- workload hints such as:
  - object size
  - archive/container classification
  - expected or observed scan cost

The system should persist enough metadata to explain why a given job used a particular recovery mode.

## Operational Guidance

Practical rule:

- if replaying `N` items is cheap, checkpoint coarsely
- if replaying `N` items is expensive, checkpoint finely

Examples:

- billions of small files:
  - default toward `batch` or `shard`
- thousands of `2GB-10GB` archives:
  - default toward `item`

## Consequences

Benefits:

- preserves durable orchestration
- uses RabbitMQ appropriately as transport rather than sole source of truth
- allows performance-sensitive workloads to avoid unnecessary precision
- supports expensive-scan workloads that need finer-grained restart behavior

Costs:

- more configuration and policy complexity
- more nuanced restart semantics
- stronger observability requirements to explain effective recovery boundaries

## Non-Goals

- not replacing PostgreSQL source-of-truth semantics with broker durability
- not guaranteeing exactly-once execution
- not removing the need for idempotent workers and tolerant downstream side effects

## Summary

DSX-Connect should remain durability-first, but it should not hardcode one restart precision for every workload.

The architecture should:

- use the Transaction Outbox Pattern for reliable producer-side handoff to RabbitMQ
- keep PostgreSQL as the canonical execution ledger
- allow recovery granularity to vary by workload cost

This preserves correctness while letting performance tuning focus on the real hot path, especially Reader-native scan execution.
