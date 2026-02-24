# Connector Model

Connectors are the integration layer between DSX-Connect and external repositories.

They are responsible for:

* Enumerating items in a repository
* Retrieving file content
* Executing remediation actions
* Exposing a consistent API contract

Connectors are intentionally stateless.
All orchestration, scanning, retry logic, scaling, and result persistence are handled by DSX-Connect Core.

This separation allows DSX-Connect to remain repository-agnostic while enabling new integrations to be added without modifying the core system.

## Standard Connector API

All connectors implement the same core API surface:

* `full_scan` — enumerate items and enqueue scan requests
* `read_file` — retrieve file content as a binary stream
* `item_action` — perform remediation (delete, move, tag, etc.)
* `webhook_event` — optional event ingestion
* `repo_check` — health validation

This uniform contract ensures consistent scanning behavior across:

* Filesystem
* AWS S3
* Azure Blob Storage
* Google Cloud Storage
* SharePoint / OneDrive
* Salesforce
* Other supported repositories


## Scan Lifecycle (Connector Interaction)

During a full scan:

1. A job is created via API or UI.
2. DSX-Connect calls the connector’s `full_scan`.
3. The connector enumerates items under its configured **asset**.
4. For each matching item, a Scan Request is created.
5. The Scan Request Worker dequeues the request.
6. The worker calls `read_file` on the connector.
7. File content is streamed to DSXA.
8. The DSXA verdict is processed.
9. If malicious, the worker calls `item_action`.
10. Results are persisted and broadcast.

Connectors never perform scanning themselves.
They provide access and remediation capabilities only.

This design enables:

* Queue-based resilience
* Horizontal worker scaling
* Retry and DLQ handling
* Repository isolation

## Filesystem Connector (Scan Lifecycle Walkthrough) 

If you completed Getting Started, you deployed a Filesystem Connector.

Because filesystems are familiar and transparent, they provide a clear illustration of how the connector model works.

![Filesystem Connector Example](../assets/dsx-connect-dataflow.svg)
*Figure 1: Filesystem Connector workflow*

Assume the connector is configured as:

```
DSXCONNECTOR_ASSET=~/Documents
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=~/Documents/quarantine
```

### Full Scan Example

When **Full Scan** is invoked:

1. DSX-Connect calls the connector’s `full_scan`.
2. The connector enumerates all files under `~/Documents`.
3. Filters (if defined) are applied.
4. For each matching file, a Scan Request is sent to DSX-Connect.
5. The Scan Request Worker calls `read_file`.
6. The file is streamed to DSXA.
7. The verdict is queued.
8. The Verdict Worker calls `item_action` if malicious.
9. The file is moved to `~/Documents/quarantine`.
10. Results are persisted and broadcast.

This flow is identical for all other connectors.

!!! note
    The DSXA Scanner sends malicious verdicts to the Deep Instinct Management Console.  The Deep Instinct Management Console should always be considered the definitive source of malicious events


The only difference is how enumeration and remediation are implemented in the connector itself.
For example, when the Filesystem Connector is asked to quarantine a file, moves the file to `~/Documents/quarantine`.
For a GCP connector, the file may be modified in place and prefixed.   Each connector will specify its own implementation.


## Why This Architecture Works

You could write a script that:

* Walks a directory
* Reads files
* Sends them to DSXA
* Moves malicious files

But that script would need:

* Retry logic
* Backoff handling
* Progress tracking
* Parallelism
* Logging
* Failure isolation

DSX-Connect provides these capabilities centrally.

Connectors remain simple:

* List files
* Read files
* Act on files

As new connectors are added, they inherit the same resilience and scaling characteristics automatically.


## Asset and Filter Model

Connectors define their scan scope using two mechanisms:

* `DSXCONNECTOR_ASSET`
* `DSXCONNECTOR_FILTER`

### Asset

`DSXCONNECTOR_ASSET` defines the exact root the connector owns. Full scans start here, and “on-access” feeds (webhooks, monitors) scope themselves to the same root. The exact meaning depends on the backend:


| Repository | Example Asset                         |
| ---------- | ------------------------------------- |
| AWS S3     | `bucket-name` or `bucket-name/prefix` |
| Azure Blob | `container-name`                      |
| GCS        | `bucket-name`                         |
| Filesystem | `/data/scan_root`                     |
| SharePoint | site or document library root         |

Asset defines the coarse boundary of enumeration.

Providers can often optimize listing operations when the asset is narrowly defined.
Providers can often narrow list operations to `name_starts_with` that root/prefix, which keeps enumeration fast (listing is usually the slowest, most serial part of a full scan). Filters (below) are applied inside the connector after the provider lists everything under the asset—most backends do not support server-side include/exclude.

Always prefer the narrowest practical asset root.

> Always set the asset to a stable, exact root — no wildcards.
> If you need multiple roots, deploy multiple connector instances.

---

### Filter

`DSXCONNECTOR_FILTER` applies rsync-like include/exclude rules under the asset.

Important:

Filters are evaluated inside the connector after enumeration.

Most providers do not support server-side include/exclude filtering beyond prefix scoping.
This means:

* The connector still lists everything under the asset.
* Filters only reduce what becomes a scan request.
* Filters do not necessarily reduce enumeration cost.

Therefore:

* Use asset for coarse partitioning.
* Use filters for fine-grained tuning.

See [Reference → Filters](../reference/filters.md) for detailed syntax.

## Asset vs Filter Best Practices

Prefer pushing boundaries into the asset:

| OK                                     | Better                                 |
| -------------------------------------- | -------------------------------------- |
| `asset=my-bucket`, `filter=prefix1/**` | `asset=my-bucket/prefix1`, `filter=""` |
| `asset=my-bucket`, `filter=sub1/*`     | `asset=my-bucket/sub1`, `filter="*"`   |

Guidance:

* Prefer **asset** for coarse boundaries (folders/prefixes/libraries).
* Use **filter** for light include/exclude tuning.
* Keep filters simple.
* Complex filters can force broad listings.

## Sharding and Scaling Strategy

For very large repositories (millions to billions of objects), a single connector instance may become enumeration-bound.

The correct scaling strategy is **asset-based sharding**.

Deploy multiple connector instances, each with a distinct asset partition.

Examples:

* S3:

    * `bucket/A`
    * `bucket/B`
    * `bucket/C`
* Time partitions:

    * `bucket/2025-01`
    * `bucket/2025-02`
* Filesystem:

    * `/data/shard1`
    * `/data/shard2`
* SharePoint:

    * Separate document libraries or folder scopes

This approach:

* Parallelizes enumeration
* Reduces list volume per connector
* Isolates failures per shard
* Aligns with horizontal worker scaling

Filter-based sharding is possible but less efficient because enumeration still occurs at the broader asset level.

Sharding becomes especially important in Kubernetes deployments where connector instances can scale horizontally.

See:

* Choosing Your Deployment
* Scaling & Performance (Kubernetes)

---

## Item Actions

`DSXCONNECTOR_ITEM_ACTION` defines what happens when a file is marked malicious.

| Value      | Behavior                         |
| ---------- | -------------------------------- |
| `nothing`  | Report only                      |
| `delete`   | Remove the object                |
| `tag`      | Apply provider-specific metadata |
| `move`     | Relocate to quarantine           |
| `move_tag` | Move and tag                     |

When using `move` or `move_tag`, configure:

`DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`

Its meaning depends on the repository (directory, prefix, folder, etc.) and connector.  As an example (filesystem connector), this setting refers to a quarantine folder within the asset root.

## Deployment Considerations

Connector scaling differs by deployment model.

In Docker Compose:

* Run multiple connector containers manually for sharding.

In Kubernetes:

* Deploy multiple releases or replicas with distinct assets.
* Combine connector sharding with worker concurrency and replica scaling.
* Use resource requests/limits and autoscaling where appropriate.

Connector strategy should align with your overall deployment model and scaling goals.

