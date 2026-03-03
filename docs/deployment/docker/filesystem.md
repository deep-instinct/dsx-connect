
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

The easiest way to deploy the Filesystem connector is by editing the `.env` file.

### 1. Set scan and quarantine paths

```bash
DSXCONNECTOR_ASSET=/mnt/DESKTOP1/share
DSXCONNECTOR_ITEM_ACTION=move
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine-DESKTOP1
````

### 2. Start the connector

```bash
docker compose -f docker-compose-filesystem-connector.yaml up -d
```
Replace docker-compose-filesystem-connector.yaml with the appropriate compose file for your environment.

That’s it.

The compose bundle will:

* Bind `${DSXCONNECTOR_ASSET}` → `/app/scan_folder`
* Bind `${DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO}` → `/app/quarantine`

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

!!! important
Keep quarantine **outside** the scan root to avoid re-scanning quarantined files.

---

## Monitoring (Recommended)

The Filesystem connector supports continuous monitoring.

Recommended defaults:

```bash
DSXCONNECTOR_MONITOR=true
DSXCONNECTOR_MONITOR_FORCE_POLLING=true
DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS=1000
```

Polling mode is recommended for:

* Docker Desktop (macOS / Windows)
* SMB / CIFS shares
* NFS mounts
* Remote filesystems where inotify events may not propagate

---

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
`.env` files alone are not sufficient for multiple services in the same project.

---

## Asset vs Filter

* **Asset** defines the coarse scan boundary (host path).
* **Filters** apply include/exclude rules under that boundary.

See:

* Core Concepts → Connector Model
* Reference → Filters
* Concepts → Performance & Throughput

---

## Storage Mounts (NFS / SMB / Remote Shares)

For instructions on mounting remote storage on the Docker host, see:

> Deployment → Docker Compose → Storage & Mounts

Remote shares must be mounted on the **host first**, then bind-mounted into the container.

---

## TLS

If DSX-Connect Core is using TLS, update:

```bash
DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586
```

See:

> Deployment → Docker Compose → TLS
