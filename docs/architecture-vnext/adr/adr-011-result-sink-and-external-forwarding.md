# ADR-011: Emit Structured Result Events to a ResultSink, Delegate Forwarding to Infrastructure

- **Status:** Proposed
- **Date:** 2026-05-22
- **Decision Owners:** DSX-Connect Architecture
- **Related:** ADR-007 (Reader Contract), ADR-009 (Capability-Based Integration Model)

## Context

DSX-Connect now models multiple distinct result families:

- `scan_result`
- `remediation_result`
- `dianna_result`
- optional `workflow_summary`

These results often need to be exported for operational visibility, SIEM ingestion, workflow integration, or archival.

In the first-generation architecture, result handling tended to collapse into one final output payload and one direct forwarding path.
That created several problems:

- core had to know too much about delivery destinations
- result timing was artificially coupled across stages
- forwarding logic threatened to become another large subsystem inside core
- application/runtime code risked taking responsibility for transport concerns better handled by logging or routing infrastructure

At the same time, many result exports are operational conveniences rather than authoritative workflow dependencies.

Examples:

- DSXA is already the source of truth for malicious scanner events
- benign full-scan reporting is often convenient, but not authoritative
- remediation and DIANNA results may need to be observed externally, but do not require DSX-Connect itself to become a general-purpose forwarding platform

The architectural goal is to keep DSX-Connect responsible for:

- authoritative state
- normalized event emission

and let external infrastructure handle:

- routing
- fan-out
- buffering
- forwarding
- filtering

## Decision

DSX-Connect will emit structured JSON result events to a **ResultSink** abstraction.

Core will not treat destination-specific forwarding as a primary orchestration responsibility.

The ResultSink abstraction exists so DSX-Connect can:

- emit normalized stage-specific result events
- remain transport-light and operationally narrow
- support multiple deployment patterns without embedding destination-specific forwarding logic into core

The exemplar deployment pattern will be:

- DSX-Connect emits structured JSON events to a local sink
- `rsyslog` ingests those events
- `rsyslog` is configured to forward, filter, archive, or drop events as needed

However, DSX-Connect is not being tightly bound to rsyslog specifically.
The architectural contract is a generic ResultSink, not a mandatory rsyslog dependency.

## Decision Drivers

- keep DSX-Connect focused on normalized state and event emission
- avoid rebuilding generic forwarding/routing inside core
- preserve stage-specific result timing
- support deployment-specific routing policy outside the application
- allow infrastructure teams to use familiar routing tools
- align with the principle that each component should do exactly one thing

## Considered Options

### Option 1: Core Performs Direct Destination Forwarding

In this model, DSX-Connect itself knows how to forward events to external targets such as syslog, HTTP endpoints, SIEM collectors, or other services.

#### Pros

- application has direct awareness of forwarding outcomes
- per-destination behavior can be modeled centrally in core
- no extra local routing component is required

#### Cons

- forwarding logic becomes another large subsystem inside core
- core accumulates destination-specific configuration and failure handling
- DSX-Connect becomes responsible for fan-out and routing concerns that infrastructure already solves well
- violates the goal of narrow component responsibility

#### Outcome

Rejected as the default architectural direction.

---

### Option 2: Emit Structured Events to a Generic ResultSink, Delegate Forwarding to Infrastructure

In this model, DSX-Connect emits normalized JSON result events to one local sink abstraction.
External infrastructure handles routing and forwarding.

#### Pros

- keeps DSX-Connect narrow and focused
- preserves stage-specific event emission
- allows rsyslog, journald, Vector, Fluent Bit, or similar tooling to handle routing
- simplifies core delivery policy to "what should be emitted", not "how should every destination behave"
- reduces destination-specific coupling inside the application

#### Cons

- core loses detailed awareness of downstream forwarding success
- forwarding audit and operational visibility move outside DSX-Connect
- strong delivery guarantees depend on sink/agent configuration

#### Outcome

Accepted.

## Clarifying Addendum: ResultSink vs Delivery Worker

The ResultSink abstraction changes the meaning of "delivery" in the architecture.

DSX-Connect should distinguish:

- **result emission**
  - normalized event leaves core
  - emitted to the ResultSink
- **external forwarding**
  - local agent or infrastructure ships the event elsewhere

Core is responsible for the first.
Infrastructure is primarily responsible for the second.

This means the old idea of a "delivery worker" evolves into a narrower concern:

- emitting a structured event to the configured sink
- not acting as a general-purpose multi-destination forwarder

## 2026 Addendum: Publish Result Events, Do Not Centralize Result Routing

The future RabbitMQ-based implementation should preserve the same boundary.

DSX-Connect should publish normalized result events once, then allow independent destination workers to subscribe to those events.
It should not grow one central result worker with destination-specific decision logic such as:

- send this result to SIEM
- send this result to webhook
- send this result to audit storage
- send this result to a customer-specific exporter
- send this result to a Deep Instinct management-plane sync path

That shape recreates the destination-aware forwarding subsystem rejected by this ADR.

The intended future pattern is:

1. scan, policy, remediation, and DIANNA stages persist authoritative DSX-Connect workflow state
2. result-worthy changes are recorded through the durable outbox
3. the relay publishes normalized result events to a RabbitMQ topic exchange
4. each destination owns its own durable queue bound to the relevant routing keys
5. each destination-specific worker consumes only its queue and owns its own retries, DLQ, credentials, formatting, and downstream delivery semantics

RabbitMQ queue ownership matters here.
Multiple consumers on the same queue compete for messages.
For pub/sub fan-out, every destination that needs a copy must have its own queue bound to the result-event exchange.

Example:

```text
outbox
  -> dsx.ng.results exchange
       -> queue: dsx.ng.results.audit-jsonl
       -> queue: dsx.ng.results.webhook.customer-a
       -> queue: dsx.ng.results.siem
       -> queue: dsx.ng.results.management-sync
```

This keeps core responsible for event production and keeps destination behavior independently deployable.

## Source-of-Truth Boundary

DSX-Connect is not intended to replace the scanner or the Deep Instinct Management Console as the authoritative scanner-result system.

For now:

- DSXA produces the scanner result
- DSXA reports scanner-side outcomes to the Deep Instinct Management Console where applicable
- the Deep Instinct Management Console remains the source of truth for scanner-result history
- DSX-Connect stores operational workflow state, job progress, connector context, policy/remediation state, and sampled result visibility

The DSX-Connect Operator Console should therefore be treated as an operational console, not the definitive scanner-result console.
It is useful for answering questions such as:

- what connector or asset produced this scan
- what job submitted it
- whether the item was read, scanned, skipped, remediated, or failed
- what sample results are visible for troubleshooting
- which worker stage is stuck or unhealthy

If future subscriber workers sync results into additional systems, those workers should be modeled as subscribers to normalized result events, not as extra branches inside the central workflow engine.

## ResultSink Contract Direction

The ResultSink should support emitting structured JSON events for:

- `scan_result`
- `remediation_result`
- `dianna_result`
- optional `workflow_summary`

Each event should carry enough normalized identity for later recombination, such as:

- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `file_hash` when known
- `scan_guid` when known
- `event_type`
- `event_time`

## Rsyslog as Exemplar Pattern

The reference deployment pattern is:

1. DSX-Connect emits structured JSON events to a local ResultSink
2. `rsyslog` ingests those events
3. `rsyslog` rules decide whether to:
   - archive locally
   - forward to SIEM
   - forward to syslog relays
   - forward to HTTP/syslog bridges
   - drop or sample selected event families

This gives operations teams a standard, configurable path without pushing that complexity into core.

## DIANNA Exception / Higher-Guarantee Paths

Most exported result events are convenience outputs rather than authoritative workflow dependencies.

However, some event families may justify stronger guarantees.
DIANNA is the primary candidate.

The ResultSink abstraction should therefore allow higher-guarantee sink implementations where needed, such as:

- durable local queue
- agent-backed guaranteed forwarding
- explicitly acknowledged sink adapters

The important architectural point is that this remains a **ResultSink concern**, not a reason to make all DSX-Connect result delivery destination-aware.

## Consequences

As a result of this decision:

- DSX-Connect should emit normalized stage-specific JSON events
- external forwarding should be treated as infrastructure, not core orchestration
- rsyslog becomes a documented reference pattern, not a hard dependency
- result routing policy shifts from application delivery rules to sink/agent configuration
- stronger guarantees for selected event families should be modeled as specialized ResultSink implementations
- future RabbitMQ fan-out should use one destination-owned queue per subscriber, not a shared result queue with competing destination workers
- destination delivery status, if surfaced later, should be tracked per subscriber rather than collapsed into one global delivery stage

## Follow-On Work

1. define the ResultSink interface and event schema
2. define a JSON event envelope for stage-specific results
3. document rsyslog example ingestion and forwarding patterns
4. decide whether the current delivery worker should become a ResultSink emitter component
5. define when, if ever, a stronger-guarantee ResultSink is required for DIANNA
6. define the RabbitMQ result-event exchange, routing keys, subscriber queue naming, and per-subscriber DLQ conventions
7. decide how much per-subscriber delivery state belongs in DSX-Connect operator visibility

## Summary

DSX-Connect should emit structured result events and stop short of becoming a destination-specific forwarding platform.

The architecture will use a generic ResultSink abstraction, with rsyslog as the reference external routing pattern.

This preserves:

- stage-specific event timing
- clean component boundaries
- deployment flexibility

while keeping forwarding complexity outside the core workflow engine.
