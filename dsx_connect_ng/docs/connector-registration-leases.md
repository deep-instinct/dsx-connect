# Connector Registration and Leases

DSX-Connect NG uses connector registration to track live connector runtimes without making those runtimes the source of truth for product policy.

The model separates durable intent from runtime presence:

```text
IntegrationRecord
  durable logical integration intent
  platform identity, policy defaults, scope ownership, operator configuration

ConnectorInstance
  runtime lease for a live connector process
  endpoint, capabilities, health, last seen time, expiry time
```

This keeps the useful 1G behavior where deployed connectors appear in the control plane, while avoiding the 1G failure mode where connector startup state becomes product configuration.

## Lifecycle

At startup, an NG-enabled connector registers its runtime instance:

```text
connector process starts
  -> builds connector instance identity
  -> determines platform and platform key
  -> advertises endpoint, version, capabilities, health, and labels
  -> POST /api/v1/control-plane/connectors/register
```

The control plane then:

1. Authenticates the registration request when enrollment auth is enabled.
2. Finds an explicit `integration_id`, or matches by `platform` and `platform_key`.
3. Creates a new `IntegrationRecord` when no logical integration exists.
4. Upserts the `ConnectorInstance`.
5. Sets `last_seen_at` and `expires_at` from the advertised lease duration.

After registration, the connector refreshes its lease:

```text
connector heartbeat interval
  -> POST /api/v1/control-plane/connectors/{connector_instance_id}/heartbeat
  -> control plane updates health, labels, capabilities, last_seen_at, expires_at
```

If heartbeat returns `404`, the connector falls back to full registration. This lets a connector recover when the control plane restarts or loses runtime lease state.

## API Surface

Connector runtime registration is part of the control-plane API:

- `POST /api/v1/control-plane/connectors/register`
- `GET /api/v1/control-plane/connectors`
- `GET /api/v1/control-plane/connectors/{connector_instance_id}`
- `POST /api/v1/control-plane/connectors/{connector_instance_id}/heartbeat`

Registration and heartbeat are machine-to-machine write operations. They may require enrollment authentication.

## Enrollment Auth

NG connector enrollment uses the same basic operational shape as 1G enrollment: the connector presents an enrollment token during registration.

Server settings:

- `DSX_CONNECT_NG__CONNECTOR_REGISTRATION_AUTH_ENABLED=true`
- `DSX_CONNECT_NG__CONNECTOR_ENROLLMENT_TOKENS=token-a,token-b`

Connector setting:

- `DSXCONNECT_ENROLLMENT_TOKEN=token-a`

HTTP header:

```text
X-Enrollment-Token: token-a
```

Auth is considered enabled when either:

- `DSX_CONNECT_NG__CONNECTOR_REGISTRATION_AUTH_ENABLED=true`, or
- `DSX_CONNECT_NG__CONNECTOR_ENROLLMENT_TOKENS` contains at least one token.

Missing or invalid tokens return `401`.

## Connector Identity

For NG, connector identity is a runtime lease identity, not a product identity.

Preferred identity sources:

1. `DSXCONNECTOR_INSTANCE_ID`
2. `POD_UID`
3. `HOSTNAME`
4. Generated in-memory UUID fallback

The legacy `connector_uuid.txt` file remains only for 1G compatibility. NG-only deployments should not need file-backed connector identity. If a connector restarts with a new `connector_instance_id`, the old runtime lease expires and the new one becomes the live instance.

## Integration Identity

The connector advertises:

- `platform`
- `platform_key`
- optional `integration_id`

`platform` identifies the platform family, such as `gcs`, `filesystem`, `sharepoint`, or `s3`.

`platform_key` is the stable tenant, project, account, bucket-family, host, or comparable platform identity.

When `integration_id` is provided, the control plane verifies that the existing integration matches `platform` and `platform_key`. A mismatch returns `409` because it would bind a runtime endpoint to the wrong logical integration.

When `integration_id` is absent, the control plane reuses an existing integration with the same `platform` and `platform_key`, or creates one.

## Capability Advertisement

The connector advertises capabilities on each registration and heartbeat.

Current capability fields are simple booleans:

- `discover`
- `enumerate`
- `monitor`
- `events`
- `read`
- `write`
- `remediate`

The connector framework infers these from registered handlers where possible.

Longer term, this should become a formal capability manifest shared by DSX-Connect NG and DSX-Transfer. That manifest should distinguish:

- supported capability: the connector implementation can do it
- granted capability: this deployment credential can do it
- requested capability: a workflow needs it

## Lease Semantics

`ConnectorInstance` is a lease, not a permanent configuration object.

Important fields:

- `connector_instance_id`
- `integration_id`
- `base_url`
- `connector_name`
- `connector_version`
- `capabilities`
- `health`
- `labels`
- `lease_seconds`
- `first_seen_at`
- `last_seen_at`
- `expires_at`

The control plane should treat a connector as live when `expires_at` is in the future.

When the lease expires:

- the logical `IntegrationRecord` remains
- protected scopes and policy remain
- historical jobs remain
- the runtime connector instance should be considered stale or unavailable

This is what allows deployment runtimes to scale, restart, and replace connector processes without deleting operator configuration.

## Product Boundaries

Connectors may advertise runtime capabilities, but they do not own product intent.

Connectors do not own:

- DSX-Connect protection policy
- DSX-Connect protected scopes
- DSX-Transfer transfer policy
- scan job orchestration
- audit identity

The shared control plane owns those concerns.

DSX-Connect NG uses registered connector instances for repository protection workflows:

```text
Discoverer -> protected scope matching
Reader -> scan content acquisition
Policy -> decision
Remediator -> repository mutation when allowed
```

DSX-Transfer should use the same registered connector inventory for guarded movement workflows:

```text
Discoverer -> planning
Reader -> source content
Scan gate -> decision
Writer -> destination commit
Audit/checkpoint -> transfer record
```

## Current Gaps

The registration and lease path exists. Remaining design and implementation work:

- define the formal shared capability manifest
- add Helm examples for NG-only and dual-registration deployments
- add enrollment-token rotation guidance
- teach workers to select eligible live connector instances instead of relying only on static proxy URL config
- define stale lease cleanup or archival behavior
