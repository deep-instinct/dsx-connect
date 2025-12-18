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

## Asset

`DSXCONNECTOR_ASSET` defines the root location that the connector owns. Full scans start here, and “on-access” feeds (webhooks, monitors) scope themselves to the same root. The exact meaning depends on the backend:

| Connector family | Typical value                                                                           | Notes                                                                          |
| --- |-----------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| AWS S3 | `bucket-name`                                                                           | Optionally include a prefix (`bucket-name/prefix`) if you want a sub-tree only. |
| Azure Blob Storage | `container-name`                                                                        | Combined with `DSXCONNECTOR_FILTER` for virtual folder scoping.                |
| Google Cloud Storage | `bucket-name`                                                                           | Behaves like S3—think of it as the top of the directory tree.                  |
| Filesystem | Relative or absolute path (`~/Documents/scan/this`, `/Users/<you>/Documents/scan/this`) | For use on local filesystems, CIFS or NFS mounts.                              |
| SharePoint / OneDrive / M365 Mail | Site/document-library, drive, or mailbox root                                           | See the connector-specific doc for precise URI requirements.                   |

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

> Filters: Use the centralized rsync‑like filter rules in Reference → [Filters](../reference/filters.md).
