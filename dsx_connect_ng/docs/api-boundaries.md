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

Connector runtime registration currently lives here:

- `POST /api/v1/control-plane/connectors/register`
- `GET /api/v1/control-plane/connectors`
- `GET /api/v1/control-plane/connectors/{connector_instance_id}`
- `POST /api/v1/control-plane/connectors/{connector_instance_id}/heartbeat`

Registration creates or links a durable integration record, then upserts a runtime connector-instance lease. It does not let connectors define protected scopes or product policy.

The shared connector framework can opt into this path with `DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true`.
For NG-only registration, `DSXCONNECTOR_INSTANCE_ID` or deployment metadata should provide the connector instance identity; the legacy `connector_uuid.txt` file is only required for 1G compatibility.

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
