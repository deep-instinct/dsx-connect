# Storage & Mounts (Docker Compose)

This page explains how to make external storage available to containers using bind mounts (local folders) or remote mounts (NFS/SMB) on the Docker host.

> Only the **Filesystem connector** requires bind-mounted storage. Most other connectors (S3, GCS, SharePoint, etc.) use remote APIs and do not require host mounts.

## Quick concept

- Docker containers can only access host storage that is explicitly mounted via `volumes:`.
- DSX-Connect Filesystem connector expects:
  - `/app/scan_folder` (read scope)
  - `/app/quarantine` (write scope)

## Bind mount (local host folder)

Example:

```yaml
services:
  filesystem-connector:
    volumes:
      - type: bind
        source: /host/data/share
        target: /app/scan_folder
      - type: bind
        source: /host/data/quarantine
        target: /app/quarantine
```

### Permissions

* The container must have read access to `/app/scan_folder`.
* The container must have write access to `/app/quarantine`.
* If you see permission errors, verify ownership/ACLs on the host and the container’s runtime user.

## Remote storage patterns

Remote mounts are configured on the **Docker host**, then bind-mounted into containers.

### NFS (Linux host)

1. Mount NFS on host:

    * `/mnt/DESKTOP1/share`
2. Bind-mount that host path into the connector container.

### SMB/CIFS (Linux host)

1. Mount SMB share on host.
2. Bind-mount the mounted directory into the container.

### macOS / Docker Desktop notes

Docker Desktop uses a VM; performance and filesystem event behavior differs from Linux.
For large shares, prefer polling mode in the Filesystem connector (see Filesystem connector docs).

## Recommended practices

* Keep quarantine **outside** the scan root to avoid re-scanning quarantined files.
* Prefer stable mount points (e.g., `/mnt/DESKTOP1/share`) and avoid user-home paths that change.
* For high scale, shard by directory (multiple connector instances, distinct mount roots).

## Related

* Filesystem Connector: `deployment/docker/connectors/filesystem.md`
* Filters: `reference/filters.md`
* Performance & Scaling: `concepts/performance.md`

