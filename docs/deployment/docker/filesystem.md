# Filesystem Connector - Docker Deployment

The Filesystem connector scans files from a directory on the Docker host.

Docker Compose relies on the host operating system’s filesystem, so any storage that the host can mount (for example NFS, SMB/CIFS, or other network filesystems) can be scanned by bind-mounting the path into the container.

!!! note "Kubernetes alternative"
    The Kubernetes deployment of the Filesystem connector can serve as a very versatile alternative when scanning volumes backed by Kubernetes `StorageClass` resources.

    This allows scanning of storage types such as NFS, CephFS, AWS EFS, Azure Files, Longhorn RWX volumes, and other CSI-backed storage systems.

    See [Filesystem Connector — Kubernetes Deployment](../kubernetes/filesystem.md) for more information.


In the official Docker Compose bundles:

- `DSXCONNECTOR_ASSET` defines the **host path** to scan.  
- Docker Compose bind-mounts that path into the container at `/app/scan_folder`.
- The connector scans `/app/scan_folder` internally.

Unlike cloud/API connectors (S3, GCS, SharePoint, etc...), the Filesystem connector requires bind-mounted storage.
See [Storage Binding](storage-mounts.md) for more information.

---

## Minimal Deployment

The following steps will install the connector with minimal configuration changes.  Read the following section for specific configuration details.

The easiest way to deploy the Filesystem connector is by editing the supplied  `sample.filesystem.env` file
and using it with the supplied `docker-compose-filesystem-connector.yaml` compose file.

### Set scan and quarantine paths
In this example, we will scan `/mnt/DESKTOP1/share` and quarantine files in `/var/lib/dsxconnect/quarantine-DESKTOP1`.  These are directories
that already exist on the Docker's host filesystem.
```bash
# sample.filesystem.env
DSXCONNECTOR_ASSET=/mnt/DESKTOP1/share
DSXCONNECTOR_ITEM_ACTION=move
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/var/lib/dsxconnect/quarantine-DESKTOP1
```

### Deploy

```bash
docker compose --env-file sample.filesystem.env -f docker-compose-filesystem-connector.yaml up -d
```
That’s it. You should now be able to see the connector in the **DSX-Connect UI**.

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

{% include-markdown "shared/connectors/filesystem/_required_settings.md" %}

---

{% include-markdown "shared/connectors/filesystem/_monitoring.md" %}

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
`.env` files alone simply become unmanagable for multiple services in the same project.

---

## Storage Mounts (NFS / SMB / Remote Shares)

For instructions on mounting remote storage on the Docker host, see:

[Storage and Mounts](storage-mounts.md)

Remote shares must be mounted on the **host first**, then bind-mounted into the container.

---

{% include-markdown "shared/_common_connector_docker_tls.md" %}

