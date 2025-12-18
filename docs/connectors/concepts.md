# Connector Concepts

Once you have the helm/docker quickstart under your belt, every connector exposes the same core configuration knobs. These shared concepts keep dsx-connect behavior consistent regardless of whether you are scanning an S3 bucket or a SharePoint site.

## Asset

`DSXCONNECTOR_ASSET` defines the root location that the connector owns. Full scans start here, and “on-access” feeds (webhooks, monitors) scope themselves to the same root. The exact meaning depends on the backend:

| Connector family | Typical value | Notes |
| --- | --- | --- |
| AWS S3 | `bucket-name` | Optionally include a prefix (`bucket-name/prefix`) if you want a sub-tree only. |
| Azure Blob Storage | `container-name` | Combined with `DSXCONNECTOR_FILTER` for virtual folder scoping. |
| Google Cloud Storage | `bucket-name` | Behaves like S3—think of it as the top of the directory tree. |
| Filesystem | Absolute path (`/mnt/share`, `/app/scan_folder`) | Defaults to the mounted `scanVolume`. |
| SharePoint / OneDrive / M365 Mail | Site/document-library, drive, or mailbox root | See the connector-specific doc for precise URI requirements. |

> Always set the asset to a stable, exact root—no wildcards. If you need multiple roots, deploy multiple connectors.

## Filter

`DSXCONNECTOR_FILTER` narrows the asset. For storage connectors this usually means subdirectories or prefixes (`logs/2025/*`). SharePoint/OneDrive filters can target libraries or change types. The semantics are connector-specific, but the intent is identical: scope work under the asset without changing the root. See [Reference → Assets & Filters](../reference/assets-and-filters.md) for examples.

## Item action policy

`DSXCONNECTOR_ITEM_ACTION` tells the connector what to do when dsx-connect marks an object malicious:

| Value | Behavior |
| --- | --- |
| `nothing` | Report only. Leave the object untouched. |
| `delete` | Remove the object. |
| `tag` | Apply provider-specific metadata/tagging (e.g., S3 object tags). |
| `move` | Relocate the object (usually to quarantine). |
| `move_tag` | Move + tag in a single workflow. |

When you pick `move` or `move_tag`, also set `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`. Interpreting that field is connector-specific (S3 key prefix, filesystem directory, SharePoint folder, etc.) but it always describes the quarantine destination.

## Putting it together

A good deployment checklist:

1. Decide on the asset root for each connector instance.
2. Add filters only when you genuinely need a sub-scope; otherwise keep it empty.
3. Pick an item action that matches your response policy and ensure the quarantine path/tag exists.

For the precise shape of each field (SharePoint site URL vs. filesystem path, etc.), jump to the connector-specific page under **Connectors → Connector Deployments**.
