# Connector Concepts

If you've run through Getting Started and deployed your first connector - a Filesystem Connector - you now have
a basic understanding of how to use all connectors. 

Every connector exposes the same API and core configuration knobs. These shared concepts keep dsx-connect behavior 
consistent regardless of whether you are scanning an S3 bucket or a SharePoint site. Now that you've stood up a 
Filesystem Connector, let's take a closer look at what happens when you run Full Scan on that connector.


## Filesystem Connector in Action

The Filesystem connector performs a full scan over a directory and can monitor for new/modified files. It implements the standard DSX‑Connector API (`full_scan`, `read_file`, `item_action`, `webhook_event`, `repo_check`) and remains stateless — scanning and decisions happen in DSX‑Connect.

The following diagram illustrates a simplified workflow of DSX-Connect, deployed with Scan Request and Verdict workers, and a Filesystem Connector.  First,
a quick overview of connector APIs relevant to this example:

- `full_scan`: enumerate items and enqueue scan requests (streaming enumeration recommended)
- `read_file`: retrieve file content (binary stream)
- `item_action`: perform remediation (delete/move/tag)


![Filesystem Connector Example](../assets/filesystem-connector-example.png)
*Figure 1: Filesystem Connector workflow*

In this example, the Filesystem Connector is deployed to scan and monitor the folder: ~/Documents, with a quarantine folder set to:
 ~/Documents/quarantine.  Step-by-step:

1. DSX-Connect triggers a `full_scan` on the connector then...
2. the connector enumerates through the file names/paths (i.e., the equivalent of an `ls` or `dir`) in ~/Documents and for each file path...
3. sends Scan Requests to DSX-Connect which queues each request.  Scan Requests are a lightweight object that contains the file path and metadata, and who (which connector) is making the request
4. DSX‑Connect Scan Request Worker dequeues a Scan Request and...
5. Requests the file from the connector (`read_file`), the connector reads the file, sends to back to the worker and...
6. the Scan Request Worker scans the file with DSXA and places the DSXA verdict in the Verdict Queue.
7. Verdict Worker dequeues a verdict and then, on a malicious verdict,...
8. calls on the connector's `item_action` to take action the connector (delete/move/tag the file). In this case, the Filesystem Connector moves the file to ~/Documents/quarantine.

Benefits of decoupling: resiliency (queue persistence), scale (parallel workers), and isolation (enumeration doesn’t block scanning).

### Why this architecture works

You may be thinking - couldn't I just write a script that scans the files and does the right thing?  And, yes, you could.  

You could build a script/application that enumerates through files and for each one encountered, read the file, scan the file and do something with the result.  You can even make it so
that this application uses advanced concepts such as multiprocessing and async IO in order to parallelize scanning for a more scalable solution.  And, you could build in functionaility for error handling such as
retries with exponential backoff and jitter, dead-letter queues for really nasty issues, and tracking where you are in a scan so that when 
a scan over millions of files fails somewhere in the middle, you can resume where you left off.

However, the DSX-Connect core gives you those pieces for free:

- **Reliability built in:** durable queues, retry with backoff, dead-letter handling, and job progress tracking.
- **Elastic scale:** independent workers for scanning and remediation; add replicas for concurrent scanning without changing connectors.
- **Separation of concerns:** connectors only enumerate/read/action; core handles orchestration, policy, logging, and metrics.
- **Consistency across backends:** the same API and semantics whether the target is a filesystem, cloud storage, or SaaS.

As you add new connectors, they inherit the same resilience and scale; each connector just focuses on integrating with its repository.

## Assets and Filters

### Asset
`DSXCONNECTOR_ASSET` defines the root location that the connector owns. Full scans start here, and “on-access” feeds (webhooks, monitors) scope themselves to the same root. The exact meaning depends on the backend:

| Connector family | Typical value                                                                           | Notes                                                                          |
| --- |-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| AWS S3 | `bucket-name`                                                                           | Optionally include a prefix (`bucket-name/prefix`) if you want a sub-tree only. |
| Azure Blob Storage | `container-name`                                                                        | Combined with `DSXCONNECTOR_FILTER` for virtual folder scoping.                |
| Google Cloud Storage | `bucket-name`                                                                           | Behaves like S3—think of it as the top of the directory tree.                  |
| Filesystem | Relative or absolute path (`~/Documents/scan/this`, `/Users/<you>/Documents/scan/this`) | For use on local filesystems, CIFS or NFS mounts.                              |
| SharePoint / OneDrive / M365 Mail | Site/document-library, drive, or mailbox root                                           | See the connector-specific doc for precise URI requirements.                   |

> Always set the asset to a stable, exact root—no wildcards. If you need multiple roots, deploy multiple connectors.

Asset is the exact scan root. Providers can often narrow list operations to `name_starts_with` that root/prefix, which keeps enumeration fast (listing is usually the slowest, most serial part of a full scan). Filters (below) are applied inside the connector after the provider lists everything under the asset—most backends do not support server-side include/exclude.

### Filter

`DSXCONNECTOR_FILTER` narrows the asset with rsync‑like include/exclude rules evaluated under the asset root.
See [Filters (Details)](../reference/filters.md) fo rmor information on filter rules. 

For connectors this usually means filtering on subdirectories or prefixes (e.g. `logs/2025/*`). The semantics are 
of how a filter works per a given connector is connector-specific, but the intent is identical: scope the files
to be scanned under the asset without changing the root.

Most repositories (S3, Blob, GCS, filesystem, SharePoint) only support narrowing via “prefix/scope” 
(asset); there is no native include/exclude filtering on list APIs, so the connector must walk every object under the 
asset during a full_scan. For example, Azure Blob only exposes container/optional-prefix list APIs — it cannot answer 
“list only PDFs or skip tmp/”. 

As such, when a connector enumerates through ASSET, filtering is applied in the connector (i.e., the connector retrieves the 
meta information on every file under ASSET and filters there).  It does not reduce 
the number files/objects that a Connector's `full_scan` has to process, just the list of files sent as scan requests 
to be scanned.

### Asset vs Filter:
  - **Asset**: exact scan root; pushes coarse scoping to the provider (fastest listing).
  - **Filter**: wildcard include/exclude under the asset; evaluated locally after listing.
- Common equivalences:
  - `asset=my-bucket`, `filter=prefix1/**`  ≈  `asset=my-bucket/prefix1`, `filter=""`
  - `asset=my-bucket`, `filter=sub1`       ≈  `asset=my-bucket/sub1`, `filter=""`
  - `asset=my-bucket`, `filter=sub1/*`     ≈  `asset=my-bucket/sub1`, `filter="*"`

### Guidance:
- Prefer **asset** for coarse boundaries (folders/prefixes/libraries) so listing stays narrow.
- Use **filter** for light include/exclude tuning under that root. Remember the connector still walks everything under the asset and filters client-side.
- Complex filters (e.g., `-tmp`) can force broad listings; whenever possible, push the boundary into the asset and keep filters simple.

## Sharding & Deployment Strategies
Use multiple assets or include‑only filters to split a large repository into smaller partitions that can be scanned in parallel by multiple connector instances.

- **Asset‑based sharding** (preferred for coarse partitions):
    - S3/GCP/Blob: `my-bucket/A`, `my-bucket/B`, … (alphabetic)
    - S3/GCP/Blob: `my-bucket/2025-01`, `my-bucket/2025-02`, … (time)
    - Filesystem: `/app/scan_folder/shard1`, `/app/scan_folder/shard2`
    - SharePoint: distinct doc libraries/folders
- **Filter‑based sharding** (include‑only filters):
    - Asset at container/bucket root, with partitions via include‑only filters (e.g., `prefix1/sub1/**`, `prefix1/sub2/**`)

> Compose POV: run multiple connector containers, each with a distinct asset partition or include‑only filter. In private K8S, deploy multiple releases with different values.

## Item Action

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

> Filters: Use the centralized rsync‑like filter rules in Reference → [Filters](../reference/filters.md).

