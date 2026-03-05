
# Filesystem Connector (Docker Compose)

The Filesystem connector scans files from a directory on the Docker host.

In the official Docker Compose bundles:

- `DSXCONNECTOR_ASSET` defines the **host path** to scan.  
- Docker Compose bind-mounts that path into the container at `/app/scan_folder`.
- The connector scans `/app/scan_folder` internally.

Unlike cloud/API connectors (S3, GCS, SharePoint, etc...), the Filesystem connector requires bind-mounted storage.
See [Storage Binding](storage-mounts.md) for more information.

---

## Quick Start (Single Instance – Recommended)

The easiest way to deploy the Filesystem connector is by editing the supplied  `sample.filesystem.env` file
and using it with the supplied `docker-compose-filesystem-connector.yaml` compose file.

### 1. Set scan and quarantine paths
In this example, we will scan `/mnt/DESKTOP1/share` and quarantine files in `/var/lib/dsxconnect/quarantine-DESKTOP1`.  These are directories
that already exist on the Docker's host filesystem.
```bash
# sample.filesystem.env
DSXCONNECTOR_ASSET=/mnt/DESKTOP1/share
DSXCONNECTOR_ITEM_ACTION=move
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine-DESKTOP1
```

### 2. Start the connector

```bash
docker compose --env-file sample.filesystem.env -f docker-compose-filesystem-connector.yaml up -d
```
That’s it.

The compose bundle will:

* Bind `${DSXCONNECTOR_ASSET}` → `/app/scan_folder` <-- internal to the filesystem connector container
* Bind `${DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO}` → `/app/quarantine` <-- internal to the filesystem connector container

---

## How the Compose Bundle Works

Excerpt from the official compose pattern:

```yaml
volumes:
  - type: bind
    source: ${DSXCONNECTOR_ASSET:-/tmp/dsxconnect-scan}
    target: /app/scan_folder
  - type: bind
    source: ${DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO:-/tmp/dsxconnect-quarantine}
    target: /app/quarantine

environment:
  DSXCONNECTOR_ASSET: ${DSXCONNECTOR_ASSET:-/tmp/dsxconnect-scan}
  DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: ${DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO:-/tmp/dsxconnect-quarantine}
```

Important:

* `DSXCONNECTOR_ASSET` is a **host path**
* The container always scans `/app/scan_folder`
* You typically do not change the container paths

---

## Required Settings

### `DSXCONNECTOR_ASSET`

Defines the host directory to scan.

Example:

```bash
DSXCONNECTOR_ASSET=/mnt/DESKTOP1/share
```

This host directory will be mounted into the container at:

```text
/app/scan_folder
```

---

### `DSXCONNECTOR_ITEM_ACTION`

Defines what happens to malicious files.

Common values:

* `nothing` (report only)
* `move` (quarantine)
* `delete`

If using `move`, also set:

```bash
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine-DESKTOP1
```

---

## Monitoring

The Filesystem connector uses the Python **`watchfiles`** library for file change detection.

Depending on how your filesystem is mounted, you may be able to use native OS file events — or you may need to force polling mode.

---

### ✅ When `DSXCONNECTOR_MONITOR=true` Is Enough

Use the default setting:

```bash
DSXCONNECTOR_MONITOR=true
```

This works **without forcing polling** when the connector has access to:

* Native Linux filesystems (ext4, xfs, etc.)
* Local macOS filesystem (running directly on macOS)
* Colima (when using virtiofs)
* WSL2 with local filesystem
* Docker on Linux host with bind-mounted local paths

In these environments, `watchfiles` can use native OS event APIs:

* Linux → inotify
* macOS → FSEvents
* Windows → ReadDirectoryChangesW

These event systems are efficient and real-time.

---

### ⚠️ When You Must Force Polling

Enable polling mode when filesystem events may **not propagate correctly** into containers:

```bash
DSXCONNECTOR_MONITOR=true
DSXCONNECTOR_MONITOR_FORCE_POLLING=true
DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS=1000
```

Polling mode is recommended for:

* Docker Desktop (macOS / Windows)
* SMB / CIFS shares
* NFS mounts
* Kubernetes Persistent Volumes backed by NFS
* Remote or network filesystems
* Any scenario where file changes are not being detected reliably

In these environments, native file system events often do **not cross VM or network boundaries**, so `watchfiles` must periodically scan for changes.

---

### 🧠 Practical Rule of Thumb

If the connector runs:

* **On the same machine as the files →** `DSXCONNECTOR_MONITOR=true` is usually fine
* **Across a VM boundary, container boundary, or network mount →** enable polling

---

### 🔍 Troubleshooting Tip

If files are not being detected:

1. Enable debug logging.
2. Temporarily force polling.
3. If polling fixes it → your filesystem does not propagate native events.


## Multiple Connector Instances (Advanced)

`.env` is ideal for a single connector instance.

If you need to scan multiple directories (for example, multiple desktops or storage mounts), you should:

1. Copy the `filesystem_connector` service block in the compose file.
2. Rename the service (e.g., `filesystem_connector_desktop1`, `filesystem_connector_desktop2`).
3. Update:

    * `ports`
    * `DSXCONNECTOR_ASSET`
    * `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`
    * `DSXCONNECTOR_CONNECTOR_URL`
    * Optional display name

Example:

```yaml
filesystem_connector_desktop1:
  ports:
    - "8620:8620"
  volumes:
    - type: bind
      source: /mnt/DESKTOP1/share
      target: /app/scan_folder
```

Multi-instance deployments require editing the compose YAML.
`.env` files alone simply become unmanagable for multiple services in the same project.

---

## Storage Mounts (NFS / SMB / Remote Shares)

For instructions on mounting remote storage on the Docker host, see:

> Deployment → Docker Compose → Storage & Mounts

Remote shares must be mounted on the **host first**, then bind-mounted into the container.

---

{% include-markdown "shared/_common_connector_docker.md" %}

