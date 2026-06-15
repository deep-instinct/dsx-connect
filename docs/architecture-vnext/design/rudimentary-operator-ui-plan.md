# Rudimentary Operator UI Plan

## Goal

Build a thin operator UI for `dsx_connect_ng` that proves the 2g control-plane model can drive real operations without inventing a second orchestration layer in the frontend.

The first UI should be:

- narrow
- API-driven
- explicitly operator-oriented
- willing to expose raw-ish state where needed

It should not attempt to be a polished product console yet.

It should also avoid becoming a deployment orchestrator for connector runtimes.

## Why Now

The 2g control boundary is stable enough to support a first UI:

- control plane owns integrations and protected scopes
- execution APIs expose jobs and job items
- policy is attached to scopes/integrations rather than connectors
- remediation is request-driven
- connectors are moving toward adapter/runtime behavior instead of policy ownership

That is enough to put a browser on top of the real APIs and use the resulting friction to identify the remaining gaps.

## Current API Surface

### Control Plane

Already present under `/api/v1/control-plane`:

- `GET /status`
- `GET /integrations`
- `POST /integrations`
- `GET /integrations/{integration_id}`
- `PATCH /integrations/{integration_id}`
- `GET /scopes`
- `POST /scopes`
- `GET /scopes/{scope_id}`
- `PATCH /scopes/{scope_id}`
- `GET /scope-match`

This is enough for a first integrations/scopes UI.

### Execution

Already present under `/api/v1/execution`:

- `GET /status`
- `GET /topology`
- `GET /jobs`
- `POST /jobs`
- `POST /jobs/batch`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/batch`
- `GET /jobs/{job_id}/items`
- `GET /job-items/{job_item_id}`
- `GET /outbox`
- `GET /outbox/{outbox_id}`
- `POST /outbox/flush`

Stage mutation endpoints also exist, but those are worker/back-end oriented rather than browser UI actions.

This is enough for a first jobs/job-items UI.

### UI Surface

Currently present under `/api/v1/ui`:

- `GET /status`

This is only a placeholder and should remain a presentation-oriented surface.

## What The First UI Should Do

The first usable console should be organized around a small set of tabbed operator views.
The tabs should expose the product model directly:

- **Assets**: what DSX-Connect can see and what is protected
- **Scan Results**: what work has run and what it found
- **Policy**: what rules exist and where they are applied

This is intentionally top-down.
The UI should begin from the operator's mental model and then use `/control-plane`, `/execution`, and `/ui` APIs to fill each view.
It should not mirror internal worker stages or queue mechanics as the primary navigation.

### Tabbed Console Model

#### Assets

Assets is the operational entry point.
It should itself be tabbed into:

- **Connectors**
- **Protected**

The **Connectors** tab shows deployed integrations and connector runtime status.
It answers:

- which connector integrations exist?
- which connector type backs each integration?
- is the connector endpoint healthy?
- what capabilities does it advertise?
- when did it last scan, sync, or report health?
- what protected scopes are attached to it?

Primary table columns:

| Column | Meaning |
| --- | --- |
| Connector | Display name / integration id |
| Type | Filesystem, S3, GCS, SharePoint, OneDrive, etc. |
| Status | Healthy, degraded, unhealthy, unknown |
| Protected scopes | Count of enabled scopes attached to the integration |
| Capabilities | Reader, discovery, remediation, result sink, etc. |
| Last activity | Last health check, scan, or job activity |

Primary actions:

- test connection
- inspect configuration
- create protected scope
- run scan
- disable integration

Initial API:

- `GET /api/v1/ui/assets/connectors`
- `POST /api/v1/ui/integrations`
- `PATCH /api/v1/ui/integrations/{integration_id}`
- `POST /api/v1/ui/integrations/{integration_id}/enabled`

This returns tab-aligned connector summaries built from integration records, scope counts, runtime config, connector capabilities, and core-side health probing.
The create/update actions are UI workflow wrappers over the control-plane service, keeping the browser pointed at product-oriented `/ui` actions rather than raw `/control-plane` contracts.

The **Protected** tab is the protected asset inventory and coverage view.
It should be filterable into a table of assets by:

- connector type
- connector integration
- asset type
- coverage state: protected, unprotected, disabled, stale, unknown
- policy
- last scan state

Protected should include both protected and unprotected assets.
That matters because the operator needs to see coverage gaps, not just configured scopes.
This view should be backed by core-side reconciliation of connector discovery results against protected scopes, as described in the [Asset Discovery Model](models/asset-discovery-model.md).

Primary table columns:

| Column | Meaning |
| --- | --- |
| Asset | Display name and normalized selector |
| Connector | Integration that reported the asset |
| Type | Bucket, prefix, folder, drive, site, share, local path, etc. |
| Coverage | Protected, unprotected, disabled, stale, unknown |
| Policy | Policy attached to the matching protected scope, if any |
| Last scan | Latest job/result summary for this asset or scope |
| Findings | Recent clean/malicious/suspicious/failed counts |

Primary actions:

- protect asset
- unprotect or disable scope
- assign policy
- scan selected
- inspect recent results

Initial API:

- `GET /api/v1/ui/assets/protected`
- `POST /api/v1/ui/assets/protected`
- `PATCH /api/v1/ui/scopes/{scope_id}`
- `POST /api/v1/ui/scopes/{scope_id}/enabled`

Supported query filters:

- `connector_type`
- `integration_id`
- `type`
- `source`
- `coverage_state`
- `limit`
- `cursor`

The response aggregates discovered assets across matching integrations and includes coverage state, matching protected scope, attached policy, unsupported integrations, failed integrations, and per-integration cursors.
The create and toggle actions use the same protected-scope validation as control-plane APIs, but expose the UI concept as "protect asset" rather than "create scope."

#### Scan Results

Scan Results shows job history, active scan progress, findings, and remediation outcomes.
It should be oriented around jobs first, with drilldown into items and stage results.

Primary table columns:

| Column | Meaning |
| --- | --- |
| Job | Job id, label, or submitted action |
| Target | Integration, protected scope, or selected assets |
| State | Accepted, running, completed, failed, cancelled, cancelling |
| Progress | Terminal count / expected count |
| Findings | Clean, malicious, suspicious, failed, cancelled |
| Remediation | Pending, completed, failed, skipped |
| Started / finished | Timing summary |

The job detail view should show:

- progress summary
- item outcomes
- scan-result details
- policy decision
- remediation action and result
- result-sink delivery state when enabled
- raw job/item JSON for debugging

Cancel should be presented with the true semantics:

- cancellation stops future publish/claim work quickly
- files already claimed into an in-memory scan batch may complete
- immediate file-level cancellation is intentionally not guaranteed in the high-throughput trusted batch mode

That tradeoff should be visible in product language but not over-explained in the main table.
The detail view can expose a short note such as "Stopping: in-flight files may finish."

Initial API:

- `GET /api/v1/ui/scan-results`

Supported query filters:

- `integration_id`
- `state`
- `limit`
- `item_limit`

The response returns tab-oriented job summaries with target metadata, progress counts, sampled finding counts, remediation state counts, timing, latest item stages, failure reason, and cooperative cancel semantics.

#### Policy

Policy shows definitions and assignments.
Policy should be managed as a control-plane concept that applies to protected assets/scopes, not as connector-owned behavior.
This follows the [Policy Attachment Model](models/policy-attachment-model.md).

Primary policy definition columns:

| Column | Meaning |
| --- | --- |
| Policy | Name / id |
| Status | Draft, active, disabled |
| Outcome rules | Summary of malicious, suspicious, unknown, unscannable actions |
| Assigned assets | Count of protected scopes/assets using the policy |
| Updated | Last changed timestamp |

Policy detail should show:

- normalized outcomes: allow, block, quarantine, hold for review, allow with audit flag, skip with reason
- quarantine target and fallback behavior where applicable
- assigned protected scopes/assets
- recent scan/remediation results governed by the policy

Primary actions:

- create policy
- edit policy
- enable/disable policy
- assign to protected assets
- inspect affected assets

Initial APIs:

- `GET /api/v1/ui/policies`
- `PUT /api/v1/ui/scopes/{scope_id}/policy`

`GET /ui/policies` is currently an aggregation over integration-level policy defaults and protected-scope `post_scan_policy`.
It groups assignments by explicit `policy_id` when available, and otherwise uses generated ids for inline scope or integration policies.
The response includes policy definition, outcome-rule summary, assigned protected assets, assignment source, and updated timestamp.

`PUT /ui/scopes/{scope_id}/policy` is the initial assignment action for the Protected assets table.
It updates the protected scope's `post_scan_policy` through the normal control-plane validation path.
This is intentionally not yet a full standalone policy-definition store; that can come after the UI clarifies the authoring and versioning workflow.

### Navigation Principles

The first UI should be dense and operational:

- tables first, cards only for summaries or repeated objects
- filters visible and predictable
- detail pages or drawers for inspection
- raw JSON available for debugging, but not the main experience
- statuses should be normalized across views

The UI should avoid treating backend implementation details as first-class product tabs.
Queues, outbox rows, stage mutations, worker topology, and raw runtime internals can be available under diagnostics, but the primary workflow is Assets -> Scan Results -> Policy.

### 1. Integrations

Support:

- list integrations
- create integration
- edit integration
- view reader/proxy configuration
- view remediation capabilities
- enable/disable integration

For the first slice, raw JSON editing for advanced `config` fields is acceptable if needed.

### 2. Protected Scopes

Support:

- list scopes
- filter scopes by integration
- create scope
- edit scope
- enable/disable scope
- configure mode: `monitor` or `full_scan`
- configure post-scan policy:
  - malicious action
  - quarantine target
  - tag-on-quarantine
  - fallback treatment

### 3. Execution / Jobs

Support:

- list jobs
- filter jobs by integration and state
- view a single job
- view batch job details
- list job items
- drill into a job item
- inspect stage results:
  - scan
  - policy
  - remediation
  - delivery
  - dianna

### 4. Health / Topology

Support:

- show control-plane backend mode
- show execution/job-bus backend mode
- show queue topology
- show connector endpoint health for configured integrations

This is the first meaningful API gap for the UI.

The UI should treat connector runtimes as externally orchestrated services that DSX-Connect binds to and validates.

For connector-owned inventory visibility and protected/unprotected reconciliation, see:

- [Asset Discovery Model](models/asset-discovery-model.md)

## What Already Works Well Enough

The following are good enough for the first UI:

- integration CRUD
- scope CRUD
- job list
- job item list
- batch submit
- stage result inspection

The UI does not need a special abstraction to start using these.

## API Gaps For A First Useful UI

### Gap 1: Browser-Friendly Health Summary

Today the browser can query `/control-plane/status` and `/execution/status`, but there is no single integration-oriented health view.

Add a UI-oriented endpoint such as:

- `GET /api/v1/ui/integrations`

Possible response shape:

```json
[
  {
    "integration": { "...": "IntegrationRecord" },
    "scope_count": 3,
    "health": {
      "connector_endpoint": "healthy | unhealthy | unknown",
      "last_checked_at": "2026-05-29T12:00:00Z",
      "details": {}
    }
  }
]
```

This should be a presentation aggregation over existing machine APIs plus connector health checks.

### Gap 2: Simple Connector Health Probe

The control plane knows connector endpoint details in integration config, but there is no normalized health check path from core.

Add either:

- a service helper inside the UI layer that probes configured connector endpoints, or
- a dedicated control-plane health helper endpoint

The frontend should not have to call connector services directly.

This also keeps the UI/control-plane boundary aligned with Kubernetes ownership of runtime lifecycle.

### Gap 3: Secret / Credential Reference Shape

The integration model currently has `config: dict`, which is flexible but not yet UI-friendly for credentials.

For the first UI, this can remain raw config, but shortly after the first slice the model should gain a more explicit shape for:

- secret reference
- tenant/account/project metadata
- auth mode
- reader proxy settings

The UI can start with a pragmatic form plus an advanced JSON section.

### Gap 4: Job Submission Convenience

`POST /execution/jobs/batch` is already sufficient, but a browser-facing UI usually wants a simpler action model such as:

- "scan this scope now"
- "scan these object identities now"

This can be handled in the UI at first by constructing `BatchJobSubmitRequest`.

No new endpoint is strictly required for v1.

### Gap 5: Pagination / Summary Views

Current list endpoints are workable, but they are still fairly raw.

Potential follow-up improvements:

- counts by state for jobs
- counts by state for items within a job
- latest activity timestamps
- last successful/failed scan/remediation summary

These are useful, but not blockers for a first UI.

## Recommended UI Architecture

### Rule 1: Keep Machine APIs Separate

Do not overload `/control-plane` and `/execution` with browser-specific response shapes.

Keep:

- `/control-plane`
- `/execution`

machine-oriented.

Add browser/operator aggregations under:

- `/ui`

### Rule 2: Thin UI Over Real APIs

The frontend should use existing control-plane and execution APIs as directly as possible.

The first UI-specific backend layer should be limited to:

- aggregation
- health enrichment
- presentation-friendly summaries
- endpoint binding and validation workflows

It should not own connector rollout, restart, or scaling behavior.

### Rule 3: Start Server-Rendered Or Lightweight Frontend

A heavy SPA is not necessary yet.

Reasonable first options:

- FastAPI-served static frontend
- lightweight HTMX/Alpine-style UI
- small React/Vite app if team preference strongly favors it

The important point is not framework choice. The important point is to keep the UI thin while the 2g contracts continue to settle.

## Recommended Implementation Sequence

### Phase 1: Minimal Operator UI

Build:

- integrations list/create/edit
- scopes list/create/edit
- jobs list/detail
- job items detail

Add one UI helper endpoint:

- `GET /api/v1/ui/integrations`

with connector-health enrichment.

This phase proves the control-plane model is workable.

### Phase 2: UX Hardening

Add:

- better forms for integration config
- better scope policy editing
- asset discovery and protected/unprotected coverage views
- status chips and stage summaries
- counts and filtering

### Phase 3: Deployment / Runtime Management

Only after the basic UI is proven:

- support connector endpoint binding workflows
- support deployment guidance generation for operators
- support secret-reference creation workflows
- support richer integration health and runtime diagnostics

This is where the "bind connector from the UI" story should mature.

## Explicit Non-Goals For The First Slice

Do not block the first UI on:

- automatic connector deployment
- connector runtime orchestration
- secret backend integration polish
- fully typed per-platform forms
- RBAC completeness
- deep dashboards
- historical analytics
- multi-tenant administration polish

Those are important later, but they should not delay proving the basic operator workflow.

## Immediate Next Steps

1. Add the first `/ui` aggregation endpoint for integrations plus connector health.
2. Choose the frontend shape:
   - server-rendered static page
   - lightweight JS app
3. Build three pages:
   - Integrations
   - Scopes
   - Jobs
4. Add connector endpoint binding/validation affordances.
5. Use the UI to drive the next round of API cleanup rather than pre-designing every missing field.

## Current Slice Status

Implemented:

- FastAPI-served static operator console at `/api/v1/ui/`
- `/api/v1/ui/integrations` aggregation with scope counts and connector-health enrichment
- `/api/v1/ui/overview` aggregation for integrations, scopes, and recent jobs
- integration create/list plus enable/disable controls
- protected scope create/list plus enable/disable controls
- single-item scan submission through `BatchJobSubmitRequest`
- scope selector scan submission through `BatchJobSubmitRequest`
- recent jobs list and raw job-item/stage inspection

Still next:

- edit forms for existing integrations and scopes beyond enable/disable
- true scan-this-scope enumeration that discovers connector objects before submitting a batch
- connector endpoint binding and validation workflow
- pagination and summarized job/item state counts
