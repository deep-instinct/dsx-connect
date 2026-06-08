# Asset Discovery Model

## Purpose

Asset discovery is the connector-owned inventory signal that tells core which platform assets are visible to an integration.

Discovery answers:

- what assets can this connector see?
- what selectors could become protected scopes?
- which existing protected scopes still map to visible assets?

Discovery does not scan content, enforce policy, or remediate objects.

## Design Principle

Keep one connector contract with optional capabilities.

Do not split connectors into separate "1g connector" and "2g connector" species. Instead:

- legacy connectors implement the existing subset
- adapted connectors advertise additional capabilities
- core uses capability discovery to decide which operator workflows are available

This keeps migration incremental and avoids forcing every connector to implement every new call at once.

## Authority Split

Connectors own:

- platform authentication and authorization
- platform-specific asset listing
- stable asset selectors
- lightweight platform metadata
- capability advertisement

Core owns:

- integrations
- protected scopes
- protection policy
- coverage reconciliation
- scan and remediation job state
- operator-facing summaries

The UI should not call connector services directly. Core should expose browser-safe UI/control-plane aggregation endpoints over connector discovery results.

## Discovery Is Not Execution

Discovery must have no scan or remediation side effects.

Allowed:

- list buckets, drives, repositories, containers, shares, sites, folders, prefixes, or equivalent top-level assets
- return stable selectors and display names
- return lightweight metadata needed for operator selection
- page through large inventories

Not allowed:

- enqueue scan jobs
- read file contents
- call scanner services
- apply tags, moves, deletes, or quarantine actions
- mutate platform state

## Capability Advertisement

Connectors should advertise whether they support asset discovery.

Example:

```json
{
  "connector": "google-cloud-storage-connector",
  "contract_version": "1.1",
  "capabilities": {
    "repo_check": true,
    "full_scan": true,
    "read_file": true,
    "item_action": true,
    "asset_discovery": true,
    "asset_types": ["bucket", "prefix", "object"]
  }
}
```

Connectors that do not support asset discovery should return a clear unsupported response rather than pretending inventory is empty.

## Connector API Shape

The framework should define a connector-owned discovery endpoint such as:

```http
GET /{connector_name}/assets?type=bucket&source=configured_asset&limit=100&cursor=...
```

Discovery can come from different connector-owned sources:

- `configured_asset`: the connector reports the currently configured repository/scope it is allowed to access
- `inventory_enumeration`: the connector enumerates broader platform inventory such as all buckets visible to the credentials

`configured_asset` is the least-privilege default for connectors that do not have tenant-wide list permissions. `inventory_enumeration` is useful when the operator wants to add new protected scopes from a broad asset list, but it may require platform permissions such as `storage.buckets.list`.

Possible response:

```json
{
  "asset_type": "bucket",
  "source": "configured_asset",
  "status": "success",
  "assets": [
    {
      "id": "lg-test-01",
      "display_name": "lg-test-01",
      "selector": "lg-test-01",
      "metadata": {}
    }
  ],
  "next_cursor": null,
  "unsupported": false,
  "message": null,
  "required_permission": null
}
```

For a prefix-capable platform, the selector may include a prefix:

```json
{
  "id": "lg-test-01/quarantine",
  "display_name": "lg-test-01/quarantine",
  "selector": "lg-test-01/quarantine",
  "metadata": {
    "bucket": "lg-test-01",
    "prefix": "quarantine"
  }
}
```

## Core API Shape

Core should proxy and normalize connector discovery for browser/operator use.

Example:

```http
GET /api/v1/ui/integrations/{integration_id}/assets?type=bucket&source=configured_asset&limit=100&cursor=...
```

Possible response:

```json
{
  "integration_id": "int_gcs",
  "asset_type": "bucket",
  "source": "inventory_enumeration",
  "status": "success",
  "assets": [
    {
      "id": "lg-test-01",
      "display_name": "lg-test-01",
      "selector": "lg-test-01",
      "coverage_state": "unprotected",
      "matching_scope_id": null,
      "metadata": {}
    }
  ],
  "next_cursor": null,
  "unsupported": false,
  "message": null,
  "required_permission": null
}
```

The core endpoint may be UI-oriented initially, but the reconciliation model should be stable enough to become a control-plane capability if operators or automation need it.

## Coverage Reconciliation

Core reconciles discovered assets against protected scopes.

Suggested states:

- `protected`: discovered asset has an enabled protected scope
- `unprotected`: discovered asset is visible but has no protected scope
- `disabled`: discovered asset has a matching disabled protected scope
- `stale`: protected scope exists but the connector no longer reports the asset
- `unknown`: connector does not support discovery or discovery failed

This makes the operator workflow explicit:

- show visible assets
- show which assets are protected
- show which assets need a protected scope
- show stale scopes that may need cleanup

## Selector Matching

Discovery responses should include a `selector` that core can use directly as a protected-scope `resource_selector`.

For path-like platforms:

- bucket selector: `bucket-a`
- prefix selector: `bucket-a/prefix/root`
- object selector: `bucket-a/prefix/root/file.txt`

For identity-like platforms:

- selector should be the stable platform identity
- display name should remain separate

Core should not infer platform-specific selector formats from display names.

## Relationship To Existing Connector Calls

`repo_check` remains a health/readiness check.

`repo_check?preview=N` may return sample objects for diagnostics, but it is not sufficient for operator asset inventory because it previews content inside the already configured repository.

`full_scan` remains execution-oriented. It may enumerate internally, but its purpose is to drive scan work. It should not be used as the asset discovery contract.

Asset discovery is a separate, non-mutating inventory capability.

## Initial Implementation Path

1. Add connector framework models and optional handler for asset discovery.
2. Implement GCS bucket discovery using the existing `gcs_client.buckets()` helper.
3. Add an NG UI/core proxy endpoint for integration asset discovery.
4. Reconcile returned selectors against protected scopes.
5. Add operator UI affordance:
   - list discovered buckets
   - show protected/unprotected state
   - create protected scope from a selected asset

## Non-Goals

Do not require every connector to implement asset discovery before the workflow exists.

Do not use discovery to scan or read content.

Do not encode GCS-specific bucket logic in core.

Do not treat an empty discovery result and an unsupported discovery capability as the same condition.
