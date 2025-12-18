# Assets (DSXCONNECTOR_ASSET) and Sharding

`DSXCONNECTOR_ASSET` defines the logical root of a connector’s scan scope. It allows you to partition a large repository into smaller “shards” so that multiple connector instances can scan in parallel (one asset partition per instance).

## What is an Asset?
- Filesystem: a mounted path (e.g., `/app/scan_folder`)
- AWS S3: `bucket` or `bucket/prefix`
- Azure Blob: `container` or `container/prefix`
- GCS: `bucket` or `bucket/prefix`
- SharePoint: a site/doc library/folder URL (scope)

Within the asset, use `DSXCONNECTOR_FILTER` to further include/exclude items. Filters are evaluated relative to the asset root.

## When to Use Assets (Sharding)
- Large repositories (many millions/billions of items)
- Need to parallelize scans across multiple connector instances
- Need to bound enumerations for fault isolation (one partition failing doesn’t block others)

### Sharding Examples
- S3: run multiple connectors, each with a distinct `DSXCONNECTOR_ASSET` such as:
  - `my-bucket/A/*`, `my-bucket/B/*`, … (alphabetic partitions)
  - `my-bucket/2025-01/*`, `my-bucket/2025-02/*`, … (time partitions)
- Filesystem: split by subfolders: `/app/scan_folder/shard1`, `/app/scan_folder/shard2`
- SharePoint: split by doc library/folder

> Compose POV: scale out by starting multiple connector containers (each pointing at a distinct asset partition). In K8S (private), you’d deploy multiple releases or replicas with distinct values.

## Filters vs Assets — Pros & Cons
- **Assets (partitioning at source):**
  - Pros: enables parallel enumeration; reduces per‑connector list volume; isolates failures per shard
  - Cons: requires coordination of partitioning (naming/scope decisions)
- **Filters (evaluation at connector):**
  - Pros: simple per‑connector scoping without changing infrastructure; expressive (rsync‑like)
  - Cons: filters are applied after listing within the asset; for very large repos, exhaustive filters can still incur heavy list operations

### Practical Guidance
- Prefer **Assets** for coarse partitioning (sharding) and scalability
- Use **Filters** for fine‑grained scoping inside an asset
- Combine both: shard by asset; refine within each partition via filters

## See Also
- Filters reference: [Filters](filters.md)
