# Filesystem Connector — Docker Compose

This guide shows how to deploy the Filesystem connector with Docker Compose for quick testing/POV. The connector itself always reads from `/app/scan_folder` and writes quarantine actions to `/app/quarantine` inside the container, so your job is simply to mount whichever filesystem you want to scan (local folder, NAS, cloud share, etc.) to those paths.

## Prerequisites
- Docker installed locally (or a container VM)
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Examples below assume the extracted folder is `dsx-connect-<core_version>/`. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- A host folder to scan (and optionally a quarantine folder), mounted into the container
- A Docker network shared with dsx‑connect (example: `dsx-connect-network`)

## Compose File
In the extracted bundle, use `dsx-connect-<core_version>/filesystem-connector-<connector_version>/docker-compose-filesystem-connector.yaml`.

### Core connector env (common across connectors)

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_DSX_CONNECT_URL` | dsx-connect base URL (e.g., `http://dsx-connect-api:8586` on the shared Docker network). |
| `DSXCONNECTOR_CONNECTOR_URL` | Callback URL dsx-connect uses to reach the connector (defaults to the service name inside the Docker network). |
| `DSXCONNECTOR_ASSET` | Host/NAS path you want to scan (bind mounted to `/app/scan_folder`). |
| `DSXCONNECTOR_FILTER` | Optional rsync-style rules evaluated relative to `/app/scan_folder`. |
| `DSXCONNECTOR_ITEM_ACTION` | What to do on malicious verdicts (`nothing`, `delete`, `move`, `move_tag`). Use `move`/`move_tag` to relocate files into the quarantine mount. |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Host/NAS path for quarantine moves (bind mounted to `/app/quarantine`). |

### Filesystem-specific settings

| Field / Env | Description |
| --- | --- |
| `DSXCONNECTOR_ASSET` | Host or NAS path you want to scan (bind mounted to `/app/scan_folder`). |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Host or NAS path for quarantined files (bind mounted to `/app/quarantine`). |
| `DSXCONNECTOR_ASSET_DISPLAY_NAME` | Overrides what the UI shows for the asset (set to the same host scan path for clarity). |
| `DSXCONNECTOR_MONITOR` | `true` to enable inotify-based monitoring of `/app/scan_folder`. |
| `DSXCONNECTOR_MONITOR_FORCE_POLLING` | `true` to poll instead of relying on inotify (useful for remote filesystems that don’t emit events). |

Copy the sample env file and edit it:
```bash
cp dsx-connect-<core_version>/filesystem-connector-<connector_version>/.sample.filesystem.env \
  dsx-connect-<core_version>/filesystem-connector-<connector_version>/.env
# edit dsx-connect-<core_version>/filesystem-connector-<connector_version>/.env:
#   DSXCONNECTOR_ASSET=/absolute/path/to/folder
#   DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=/absolute/path/to/folder/dsxconnect-quarantine
```

Deploy:
```bash
docker compose --env-file dsx-connect-<core_version>/filesystem-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/filesystem-connector-<connector_version>/docker-compose-filesystem-connector.yaml up -d
```

No changes to the compose file are required beyond the env values—the connector always operates on `/app/scan_folder` inside the container, with `DSXCONNECTOR_ASSET` supplying the host path to bind-mount. To keep the dsx-connect UI readable, set `DSXCONNECTOR_ASSET_DISPLAY_NAME` to the same host scan path.

### Local vs Remote Mounts
- **Local bind mounts** (default compose file): use `DSXCONNECTOR_ASSET` / `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` so Docker binds host directories into `/app/scan_folder` and `/app/quarantine`.
- **Remote/NAS mounts**: swap the scan volume with an NFS or SMB volume before binding to `/app/scan_folder`. The quarantine path can remain a local bind if desired, or also point to a NAS export.

Example NFS compose snippet (`docker-compose-filesystem-connector-nfs.yaml`):

```yaml
volumes:
  nfs_mount:
    driver: local
    driver_opts:
      type: "nfs"
      o: "addr=192.168.86.44,vers=3,nolock,tcp,resvport"
      device: ":/mnt/fileshare/scanshare"

services:
  filesystem_connector:
    volumes:
      - nfs_mount:/app/scan_folder
      - type: bind
        source: *quarantine-folder
        target: /app/quarantine
```

Update the `addr`, `device`, and NFS options to match your NAS. This mounts the remote export inside the container so `DSXCONNECTOR_ASSET=/app/scan_folder` still works unchanged.

Example SMB/CIFS snippet (requires `cifs-utils` on the Docker host):

```yaml
volumes:
  smb_mount:
    driver: local
    driver_opts:
      type: cifs
      o: "username=svcaccount,password=changeme,vers=3.0,uid=1000,gid=1000"
      device: "//fileserver01/share/scans"

services:
  filesystem_connector:
    volumes:
      - smb_mount:/app/scan_folder
      - type: bind
        source: *quarantine-folder
        target: /app/quarantine
```

Adjust the credentials, share path, and `uid/gid` to match your environment. CIFS behaves like any other bind once mounted inside the container.

Example AFS (OpenAFS) snippet (requires the host to have `openafs-client` and a mounted `/afs` tree):

```yaml
services:
  filesystem_connector:
    volumes:
      - type: bind
        source: /afs/yourcell.com/projects/scans
        target: /app/scan_folder
      - type: bind
        source: *quarantine-folder
        target: /app/quarantine
```

Make sure the Docker host’s AFS cache manager has tokens for the target path (`kinit` + `aklog`), and adjust the `/afs/...` path to match your cell. Once bound, the connector treats `/app/scan_folder` like any other volume.

## Assets and Filters
- `DSXCONNECTOR_ASSET` is the host/NAS path; the compose file bind-mounts it to `/app/scan_folder` where the connector actually scans.
- For quarantine actions, mount a second host path (e.g., `./quarantine:/app/quarantine`) and set `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` to that same host path (the connector maps it to `/app/quarantine` internally when the mount exists).
- To avoid rescanning quarantined items, keep the quarantine folder outside the scanned path (or rely on the connector’s built-in skip list for the configured quarantine path).
- Filters are evaluated relative to `/app/scan_folder` inside the container; they do **not** reference host paths directly.
- See Reference → [Assets & Filters](../../reference/assets.md) for guidance on sharding and scoping.

## Webhook Exposure
Expose or tunnel the host port mapped to `8620` when dsx-connect (or other internal services) must reach private connector routes. Keep `DSXCONNECTOR_CONNECTOR_URL` set to the Docker-network hostname (e.g., `http://filesystem-connector:8620`) so dsx-connect resolves the service internally, and forward the host port through your preferred tunnel only for inbound events that originate outside Docker.

## TLS Options
See [Deploying with SSL/TLS](./tls.md) for Docker Compose examples (core + connectors), including runtime-mounted certs and local-dev self-signed cert generation.

## Notes
- Consider enabling monitor (`DSXCONNECTOR_MONITOR=true`) for real-time file change detection.
- If you can mount the storage into `/app/scan_folder`, the connector can scan it—local disks, NAS shares, and remote filesystems all work once bound.
