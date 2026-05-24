# Result Sink Model

## Purpose

This document defines the intended `ResultSink` abstraction for DSX-Connect.

The ResultSink exists so DSX-Connect can emit normalized stage-specific JSON result events without becoming a destination-specific forwarding platform.

For the architectural decision behind this direction, see:

- `adr/adr-011-result-sink-and-external-forwarding.md`
- `design/result-sink-examples.md`

---

## Core Principle

DSX-Connect should own:

- authoritative workflow state
- normalized result event production

Infrastructure should primarily own:

- routing
- fan-out
- forwarding
- archive policies
- destination-specific transforms

---

## ResultSink Responsibilities

A ResultSink is responsible for:

- accepting normalized result events from core
- serializing them as structured JSON
- writing them to a configured local sink
- optionally applying stronger durability/acknowledgement behavior for selected event families

A ResultSink is not inherently responsible for:

- interpreting policy
- deciding which workflow stages should run
- owning parent/job completion state
- serving as a generic destination-specific integration layer

---

## Event Families

The ResultSink should support at least:

- `scan_result`
- `remediation_result`
- `dianna_result`
- optional `workflow_summary`

Each event family is emitted when its corresponding result becomes available.

---

## Current `scan_result` Envelope

The current `scan_result` emission shape is intentionally consumer-friendly.

It includes:

- stable identity and correlation fields
- top-level scan outcome convenience fields
- stage payload content
- scanner/reader metadata useful for operational analysis

Current shape:

```json
{
  "schema_version": "1.0",
  "event_type": "scan_result",
  "event_time": "2026-05-22T14:00:00Z",
  "job_id": "job-123",
  "job_item_id": "item-456",
  "integration_id": "sharepoint-prod",
  "scope_id": "scope-finance",
  "object_identity": "drive:abc/item:def",
  "file_hash": "abc123",
  "scan_guid": "scan-789",
  "verdict": "Benign",
  "file_type": "Unknown",
  "content_source_mode": "original",
  "scanner_metadata": {
    "source": "dsxa",
    "reader": "connector_proxy",
    "readerElapsedMs": 17.8,
    "dsxaElapsedMs": 1325.7,
    "requestElapsedMs": 1343.4
  },
  "payload": {
    "verdict": "Benign",
    "fileType": "Unknown",
    "scanGuid": "scan-789",
    "details": {
      "fileInfo": {
        "file_hash": "abc123",
        "file_type": "Unknown"
      }
    },
    "scannerMetadata": {
      "source": "dsxa",
      "reader": "connector_proxy"
    }
  }
}
```

For non-summary events:

- `workflow_summary` is omitted

For `workflow_summary` events:

- the event may additionally include the full summary blob under `workflow_summary`

## Stability Guidance

Treat these fields as the stable consumer contract:

- `schema_version`
- `event_type`
- `event_time`
- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `file_hash`
- `scan_guid`
- `verdict`
- `file_type`
- `content_source_mode`
- `payload`

Treat `scanner_metadata` as operationally useful but implementation-shaped:

- suitable for collectors, debugging, and analytics
- may gain fields over time
- should remain structured JSON rather than opaque strings

The exact schema may still evolve, but the envelope should remain:

- structured
- typed by `event_type`
- sufficient for downstream recombination

---

## Rsyslog Exemplar Pattern

The exemplar operational pattern is:

1. DSX-Connect emits JSON lines to a local file, stdout stream, syslog socket, or similar sink
2. `rsyslog` ingests those events
3. `rsyslog` rules decide whether to:
   - archive locally
   - forward to SIEM
   - forward to syslog relay
   - forward to another agent or pipeline
   - suppress selected event families

This makes rsyslog the routing/fan-out layer, not DSX-Connect core.

---

## Candidate ResultSink Implementations

Possible implementations include:

- `JsonFileResultSink`
- `StdoutResultSink`
- `SyslogResultSink`
- `DurableQueueResultSink`

Different deployments may choose different implementations without changing the core event model.

The same applies to the downstream collector/router layer.

DSX-Connect should remain compatible with multiple external forwarding agents because the contract is:

- structured JSON result emission
- not a hard-coded collector choice

Vector is the current reference example because it supports richer structured transforms if later aggregation or recombination is needed outside core.
That is a recommendation, not an architectural requirement.

---

## Delivery Guarantees

Most emitted result events are convenience outputs.

That means many deployments can accept:

- best-effort local emission
- forwarding managed by rsyslog or another agent

However, specific event families may justify stronger guarantees.

Current likely candidate:

- `dianna_result`

That stronger guarantee should be modeled as:

- a different ResultSink implementation
- or a differently configured local agent path

not as a reason to make all result emission destination-aware in core.

---

## Relationship to Workflow State

Result emission should not be confused with authoritative workflow completion.

For example:

- `scan_result` emission does not imply the item is fully completed
- `workflow_summary` emission may align with later completion semantics
- authoritative workflow state remains in Postgres-backed job/item/stage records

---

## Open Questions

- Should `workflow_summary` remain optional or become a standard event family?
- Which default ResultSink should local development use?
- Should DIANNA use a separate stronger-guarantee sink by default, or only when configured?
