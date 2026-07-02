# Architecture

DSX-Connect NG is a separate application boundary for the next-generation DSX-Connect architecture.

It should not import from legacy `dsx_connect.*` or reuse legacy database tables.

## Application Shape

```text
FastAPI app
  |
  +-- control-plane routes
  +-- execution routes
  +-- UI routes
  +-- health routes

ControlPlaneService
  |
  +-- memory repository for tests/local
  +-- PostgreSQL repository for durable mode

JobService
  |
  +-- memory/PostgreSQL job repository
  +-- memory/RabbitMQ job bus
```

## Workers

Workers consume typed messages and update durable job state:

- relay worker
- scan worker
- policy worker
- remediation worker
- result-sink worker
- DIANNA worker

The worker protocol should stay stable even as implementations move from stubs to real services.

## Result Delivery

The result-sink worker is the preferred naming for structured output. `delivery-worker` remains as a compatibility alias while the rename settles.

Supported result sink backends currently include:

- stdout
- JSON lines

## Reader Boundary

The scan worker uses worker-hosted readers. Reader strategy is resolved from request overrides, integration config, and settings.

Supported strategies today:

- native
- proxy
- cached
- quarantine

Proxy reader stages connector-compatible read responses to local temp files for DSXA scanning.

## Connector Capability Model

DSX-Connect NG should consume connector capabilities rather than treating connectors as monoliths.

Shared design rule:

```text
Products orchestrate workflows.
Connectors expose platform capabilities.
Shared contracts define capability boundaries.
```

For DSX-Connect NG, the relevant connector capabilities are usually:

- `Discoverer` for asset inventory and protected scope reconciliation
- `Reader` for scan content acquisition
- `Remediator` for delete, move, tag, quarantine, or permission changes
- `EventSource` for future incremental/event-driven workflows
- `IdentityResolver` for stable object identity
- `CredentialProvider` for platform auth
- `CapabilityManifest` for supported operations and limits

The shared model is documented in [connector-capability-model.md](../../../docs/architecture-vnext/design/connector-capability-model.md).

## Shared Control Plane Direction

Connector registration should be part of the NG control-plane model, not a DSX-Connect-only legacy behavior.

The target shape is:

```text
connectors register runtime instances and capabilities
  -> shared DSX control plane stores integration identity, health, and capability inventory
  -> DSX-Connect NG composes Discoverer / Reader / Remediator capabilities
  -> DSX-Transfer composes Discoverer / Reader / Writer capabilities
```

`IntegrationRecord` remains the logical source of truth for product intent. `ConnectorInstance` represents a live runtime endpoint, including base URL, version, capabilities, health, and last-seen lease data.

Manual/static integrations should remain supported for local development and pre-provisioning, but deployed connectors should be able to self-register and refresh their runtime status.

See [shared-control-plane.md](shared-control-plane.md).
