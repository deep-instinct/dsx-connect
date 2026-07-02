# Shared Connector Control Plane

DSX-Connect NG should evolve into the shared control plane for connector-backed workflows.

The control plane should not be scan-specific. It should own connector registration, integration identity, capability inventory, health, enrollment, and durable workflow configuration so multiple products can compose the same connector capabilities.

```text
Connectors
  -> register runtime instances and capabilities
  -> expose Discoverer / Reader / Writer / Remediator / EventSource surfaces

Shared control plane
  -> stores integrations, protected scopes, connector instances, capabilities, health
  -> owns enrollment, policy attachment, workflow intent, and audit identity

DSX-Connect NG
  -> uses Discoverer / Reader / Remediator for protected repository scanning

DSX-Transfer
  -> uses Discoverer / Reader / Writer for guarded copy, sync, move, and migration
```

## Registration Model

Connectors should be able to register themselves with the control plane when they start.

Registration is a runtime assertion:

- this connector instance is alive
- this is its reachable endpoint
- this is its connector version
- this is the platform or platform family it supports
- these are its supported and granted capabilities
- these are its operational limits
- this is the integration identity it belongs to, or proposes

The durable integration record remains the logical source of truth for product intent:

- platform identity
- protected scopes or transfer endpoints
- policy defaults
- secret references
- workflow configuration
- operator ownership

This preserves the useful 1G behavior where connectors appear after deployment, without making the connector own product policy.

## Core Objects

`IntegrationRecord` is the logical platform binding.

Examples:

- GCS project or bucket family
- filesystem share/root
- SharePoint tenant/site
- S3 account/bucket family

`ConnectorInstance` should be the runtime binding.

Expected fields:

- `connector_instance_id`
- `integration_id`
- `platform`
- `platform_key`
- `base_url`
- `connector_name`
- `connector_version`
- `capabilities`
- `health`
- `last_seen_at`
- `expires_at`
- deployment labels such as namespace, pod, region, or runner

Multiple connector instances may serve one integration when the deployment is scaled or split by region.

## Supported Modes

The control plane should support both runtime registration and explicit configuration.

Runtime registration is preferred for deployed connectors:

```text
connector starts
  -> POST /api/v1/control-plane/connectors/register
  -> control plane authenticates enrollment
  -> control plane upserts ConnectorInstance
  -> control plane creates or links IntegrationRecord
  -> connector heartbeats
  -> stale instances expire
```

Explicit configuration remains useful for:

- local development
- tests and demos
- air-gapped imports
- operators who want to pre-create integrations before runtime exists

These modes should converge on the same records. Manual configuration should not create a separate connector model.

## Product Composition

DSX-Connect NG composes connector capabilities for repository protection:

```text
Discoverer -> protected scope matching
Reader -> scan content acquisition
Policy -> allow/block/remediate decision
Remediator -> repository mutation when policy allows
```

DSX-Transfer composes connector capabilities for guarded movement:

```text
Source Discoverer -> transfer planning
Source Reader -> content stream
Scan gate -> allow/block decision
Destination Writer -> destination commit
Audit/checkpoint -> transfer record
```

This means DSX-Transfer should use the same connector registration and capability inventory instead of building a second connector registry.

## Boundary Rules

- Products orchestrate workflows.
- Connectors expose platform capabilities.
- The shared control plane owns integration identity, enrollment, policy attachment, health, and audit identity.
- Connectors do not own DSX-Connect policy.
- Connectors do not own DSX-Transfer transfer policy.
- Writer contracts must not inherit DSX-Connect remediation assumptions.
- Remediation contracts must not assume every destination is a transfer sink.

## Implementation Status

Initial NG support now includes:

- `ConnectorInstance` model, repository, service, and PostgreSQL migration.
- `POST /api/v1/control-plane/connectors/register` for runtime registration.
- `POST /api/v1/control-plane/connectors/{connector_instance_id}/heartbeat` for lease refresh.
- UI summaries that show logical integrations and live connector instances together.
- Connector framework support for opt-in NG registration and heartbeat.

Connector-side opt-in settings use the existing `DSXCONNECTOR_` prefix:

- `DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true`
- `DSXCONNECTOR_DSX_CONNECT_NG_URL=http://dsx-connect-ng:8091`
- `DSXCONNECTOR_INSTANCE_ID=...` for a deployment-native connector instance ID
- `DSXCONNECTOR_NG_INTEGRATION_ID=...` when linking to a pre-created integration
- `DSXCONNECTOR_NG_PLATFORM=...` when the inferred platform name is not specific enough
- `DSXCONNECTOR_NG_PLATFORM_KEY=...` for the stable tenant/project/account key
- `DSXCONNECTOR_NG_CONNECTOR_LABELS='{"namespace":"dsx-connect"}'`
- `DSXCONNECTOR_NG_LEASE_SECONDS=120`

During migration a connector may register with 1G, NG, both, or neither:

```text
1G only: DSXCONNECTOR_REGISTER_WITH_CORE=true
NG only: DSXCONNECTOR_REGISTER_WITH_CORE=false + DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE=true
dual:    both true
local:   both false
```

For NG-only deployments, connector identity should be deployment-native rather than file-backed. The connector framework uses `DSXCONNECTOR_INSTANCE_ID` when provided, then `POD_UID` or `HOSTNAME`, and only falls back to an in-memory generated UUID. The legacy `connector_uuid.txt` file remains only for 1G compatibility, where stable UUID persistence is still part of the Redis/HMAC registration flow.

Remaining near-term work:

1. Add enrollment-token authentication for connector registration.
2. Define a formal capability manifest contract shared by DSX-Connect NG and DSX-Transfer.
3. Teach worker capability selection to choose eligible connector instances instead of assuming a static proxy URL.
4. Add Helm examples for NG-only and dual-registration deployments.

The current `IntegrationRecord` and capability config should remain intact. Registration should populate and refresh runtime binding data around it.
