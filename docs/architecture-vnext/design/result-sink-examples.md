# Result Sink Examples

## Purpose

This document gives concrete example deployment patterns for forwarding DSX-Connect result events after they are emitted to a local `ResultSink`.

These examples are intentionally **operational patterns**, not core architecture requirements.

For the architectural model, see:

- `adr/adr-011-result-sink-and-external-forwarding.md`
- `design/models/result-sink-model.md`

---

## Recommended Local Emission Pattern

For local development and simple deployments:

- DSX-Connect emits structured JSON events to:
  - `StdoutResultSink`
  - or `JsonLinesResultSink`

For collector-based forwarding, the recommended example pattern is:

- `JsonLinesResultSink`
- `Vector` tails the file
- `Vector` forwards to the chosen downstream platform

Checked-in example configs live under:

- `dsx_connect_ng/examples/vector/vector-console.yaml`
- `dsx_connect_ng/examples/vector/vector-splunk-hec.yaml`
- `dsx_connect_ng/examples/vector/vector-chronicle.yaml`
- `dsx_connect_ng/examples/vector/README.md`

This keeps DSX-Connect itself agnostic about the final destination.

### Why Vector Is the Current Exemplar

The recommendation here is not based on licensing or lock-in.
It is based on where we expect responsibility to live over time.

Vector is the current exemplar because:

- DSX-Connect emits structured stage events rather than one final combined blob
- later recombination, routing, and reshaping should happen **after** workflow execution
- Vector is well-suited for structured transforms, field-based routing, and multi-sink forwarding

Compared with alternatives:

- `rsyslog`
  - excellent for classic log routing and forwarding
  - less attractive if the pipeline is expected to evolve into richer structured transforms
- `Fluent Bit`
  - strong lightweight collector/forwarder
  - still a valid option
  - less compelling as the reference example when post-processing flexibility is expected to grow

So the decision basis is:

- keep DSX-Connect narrow
- emit normalized JSON events
- let an external event pipeline reshape or recombine them later

That makes Vector the best current **example**, without making it a core dependency.

### Swapability

Because DSX-Connect emits to a generic `ResultSink` abstraction, the collector choice remains swappable later.

That means the deployment can move between:

- `Vector`
- `rsyslog`
- `Fluent Bit`
- another compatible agent

without changing the core event model inside DSX-Connect.

---

## Example: Vector to Splunk HEC

### When to Use

Use this pattern when:

- Splunk is the downstream SIEM
- you want a common, recognizable integration example
- you want a collector that already has a native Splunk HEC log sink

### DSX-Connect Local Sink

Example DSX-Connect settings:

```bash
DSX_CONNECT_NG_RESULT_SINK__BACKEND=json_lines
DSX_CONNECT_NG_RESULT_SINK__PATH=/var/log/dsx-connect-ng/results.jsonl
```

### Vector Config Shape

```yaml
See:

- `dsx_connect_ng/examples/vector/vector-splunk-hec.yaml`
```

### Why This Works Well

- Vector has a dedicated `splunk_hec_logs` sink
- Splunk HEC is a standard operational destination
- DSX-Connect remains responsible only for normalized event production

### Notes

- stage-specific routing can still be done in Vector based on `event_type`
- if only certain event families should go to Splunk, that filter belongs in the collector config

---

## Example: Vector to Google SecOps / Chronicle

### When to Use

Use this pattern when:

- Google SecOps / Chronicle is the downstream SIEM
- a customer environment already standardizes on Chronicle
- you want a modern, cloud-native forwarding example

### DSX-Connect Local Sink

Example DSX-Connect settings:

```bash
DSX_CONNECT_NG_RESULT_SINK__BACKEND=json_lines
DSX_CONNECT_NG_RESULT_SINK__PATH=/var/log/dsx-connect-ng/results.jsonl
```

### Vector Config Shape

```yaml
See:

- `dsx_connect_ng/examples/vector/vector-chronicle.yaml`
```

### Why This Works Well

- Vector has a dedicated `gcp_chronicle_unstructured` sink
- Chronicle remains a downstream destination, not a core DSX-Connect concern
- routing logic still lives in the collector layer

### Notes

- this example uses Chronicle’s unstructured path as the simpler initial pattern
- if specific event families later justify tighter schema or stronger guarantees, that should evolve in the ResultSink/collector layer, not in the scan/remediation/DIANNA workers

---

## Choosing Between the Two Examples

- choose **Splunk HEC** when you want the most familiar SIEM forwarding example
- choose **Chronicle** when a customer deployment or strategic environment makes it the more relevant reference

The core DSX-Connect architecture is identical in either case:

1. emit normalized result event
2. collector ingests it
3. collector forwards it

---

## Local Debug Example

For local development, the simplest collector path is:

- `JsonLinesResultSink`
- `Vector`
- console sink

Use:

- `dsx_connect_ng/examples/vector/vector-console.yaml`

This example is intentionally useful even before any SIEM forwarding is configured, because it lets you watch normalized result events as they are emitted.

---

## Stronger-Guarantee Note for DIANNA

If `dianna_result` later requires stronger guarantees than other event families, the preferred place to solve that is:

- a stronger ResultSink implementation
- or a collector path with stronger acknowledgement/buffering behavior

not by making DSX-Connect core destination-aware.
