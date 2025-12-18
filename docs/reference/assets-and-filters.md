# Assets & Filters (Sharding and Scoping)

This page explains how to choose and combine `DSXCONNECTOR_ASSET` (the exact scan root) and `DSXCONNECTOR_FILTER` (rsync‑like scoping) across connectors. It also covers sharding large repositories for parallel scans.

## Assets (DSXCONNECTOR_ASSET)
`DSXCONNECTOR_ASSET` defines the exact root of a scan — no wildcards.

- Filesystem: a mounted path (e.g., `/app/scan_folder`)
- AWS S3: `bucket` or `bucket/prefix`
- Azure Blob: `container` or `container/prefix`
- GCS: `bucket` or `bucket/prefix`
- SharePoint: a site/doc library/folder URL (scope)

Use filters to further include/exclude items under the asset root (see below). Filters are evaluated relative to the asset and run **inside the connector**; the provider still lists everything under the asset root, and the connector drops items client-side. Most repositories (S3, Blob, GCS, filesystem, SharePoint) only support narrowing via “prefix/scope” (`asset`); there is no native include/exclude filtering on list APIs, so the connector must walk every object under the asset during a full_scan. For example, Azure Blob only exposes `container/optional-prefix` list APIs — it cannot answer “list only PDFs or skip tmp/”. That filtering happens locally in the connector after Azure returns every blob in the asset scope.

## Filters (DSXCONNECTOR_FILTER)
Rsync‑like include/exclude rules evaluated under the asset root. See [Filters (Details)](filters.md) for the full reference.

## Asset vs Filter
- **Asset**: exact scan root; provider can often narrow list operations to `name_starts_with` that root/prefix.
- **Filter**: expressive rsync‑style rules under the asset; wildcard selection and excludes.

### Equivalences
- `asset=my-container`, `filter=prefix1/**`  ≈  `asset=my-container/prefix1`, `filter=""`
- `asset=my-container`, `filter=sub1`       ≈  `asset=my-container/sub1`, `filter=""`
- `asset=my-container`, `filter=sub1/*`     ≈  `asset=my-container/sub1`, `filter="*"`

### Guidance
- Prefer **Asset** for the stable, exact root of a scan (fast provider narrowing; simpler mental model). When the asset is narrow, the provider only returns the relevant subset and the connector spends less time listing. This matters because listing (full_scan) is typically the most expensive, inherently serial connector operation.
- Use **Filter** for wildcard selection and excludes under that root, but remember the connector still has to fetch all objects beneath the asset and then evaluate filters locally.
- Complex filters (e.g., excludes like `-tmp`) can force broader provider listings with lots of client-side filtering. Whenever possible, push coarse boundaries into the asset (e.g., `asset=my-bucket/prefix1`) and keep filters for light-touch adjustments.

## Sharding & Deployment Strategies
Use multiple assets or include‑only filters to split a large repository into smaller partitions that can be scanned in parallel by multiple connector instances.

- **Asset‑based sharding** (preferred for coarse partitions):
  - S3: `my-bucket/A`, `my-bucket/B`, … (alphabetic)
  - S3: `my-bucket/2025-01`, `my-bucket/2025-02`, … (time)
  - Filesystem: `/app/scan_folder/shard1`, `/app/scan_folder/shard2`
  - SharePoint: distinct doc libraries/folders
- **Filter‑based sharding** (include‑only filters):
  - Asset at container/bucket root, with partitions via include‑only filters (e.g., `prefix1/sub1/**`, `prefix1/sub2/**`)

> Compose POV: run multiple connector containers, each with a distinct asset partition or include‑only filter. In private K8S, deploy multiple releases with different values.

## See Also
- [Filters (Details)](filters.md)
