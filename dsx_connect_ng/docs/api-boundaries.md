# API Boundaries

DSX-Connect NG keeps three API families separate.

## Control Plane

Namespace:

```text
/api/v1/control-plane/...
```

Purpose:

- integration registration
- protected scope management
- connector health and capability metadata
- policy attachment
- protection model management

Characteristics:

- stable machine contract
- automation friendly
- no frontend-shaped assumptions

## Execution

Namespace:

```text
/api/v1/execution/...
```

Purpose:

- scan submission
- job and job-item state
- worker/backend execution contracts
- remediation execution contracts
- result handoff

Characteristics:

- reliability boundary for the scan path
- stable machine contract
- no presentation-oriented convenience payloads

## UI

Namespace:

```text
/api/v1/ui/...
```

Purpose:

- browser/operator console workflows
- human-facing summaries
- frontend convenience aggregation

Characteristics:

- may compose multiple backend records
- may evolve faster than machine contracts
- must not become the worker or connector integration contract

## Rule

If a contract exists so a worker, connector, or backend service can do work, it belongs under execution or control-plane, not UI.
