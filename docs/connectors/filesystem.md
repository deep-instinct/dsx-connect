# Filesystem Connector

The **Filesystem connector** scans files from a mounted filesystem.

Unlike cloud/API connectors (such as S3, Google Cloud Storage, or SharePoint), this connector operates directly on a **directory exposed to the container**.

Files are scanned from:

```

/app/scan_folder

```

The connector monitors this directory and sends files to DSX for scanning.

---

## When to Use the Filesystem Connector

Use this connector when scanning files stored in:

- local disks
- Windows file shares (SMB / CIFS)
- NFS mounts
- NAS devices
- Kubernetes persistent volumes
- container host storage

Because the connector simply scans a filesystem path, **any storage that can be mounted into the container can be scanned**.

---

## How It Works

The Filesystem connector scans files from a directory **mounted into the container**.

Inside the container, this directory is always exposed at:
`/app/scan_folder`


The connector monitors this internal path and sends detected files to DSX for scanning.

The actual storage location depends on the deployment platform:

| Platform | Storage Source |
|--------|--------|
| Docker Compose | Bind-mounted host directory |
| Kubernetes | PersistentVolume or other CSI-backed storage |

For example:

- Docker → `/mnt/share` on the host → `/app/scan_folder` in the container
- Kubernetes → PVC mount → `/app/scan_folder`

File monitoring is implemented using the Python **`watchfiles`** library.

Depending on the storage backend, file change detection may use:

- native OS filesystem events
- polling-based monitoring

Native event systems include:

- Linux → `inotify`
- macOS → `FSEvents`
- Windows → `ReadDirectoryChangesW`

Some network filesystems do not propagate filesystem events correctly.  
In these environments polling mode may be required.

---

## Connector Root Directory

All Filesystem connector deployments scan the directory:

```

/app/scan_folder

```

How that directory is populated depends on the deployment platform:

| Platform | How storage is mounted |
|--------|--------|
| Docker Compose | Bind mount from host filesystem |
| Kubernetes | PersistentVolume / PersistentVolumeClaim |

---

## Deployment Options

Choose the deployment method appropriate for your environment.

=== "Docker Compose"

    The Docker deployment bind-mounts a directory from the container host.

    Typical use cases include:

    - scanning local directories
    - scanning mounted SMB / NFS shares
    - scanning NAS storage

    See:

    ➜ [Filesystem Connector — Docker Deployment](../../deployment/docker/filesystem.md)

=== "Kubernetes (Helm)"

    Kubernetes deployments mount storage through a **PersistentVolumeClaim (PVC)** or other CSI-backed storage.

    This allows scanning storage such as:

    - NFS
    - AWS EFS
    - Azure Files
    - CephFS
    - Longhorn RWX volumes
    - other Kubernetes storage classes

    See:

    ➜ [Filesystem Connector — Kubernetes Deployment](../../deployment/kubernetes/filesystem.md)

---

## Scaling Considerations

The Filesystem connector can be scaled horizontally, but behavior depends on the storage backend.

When multiple connector replicas scan the **same filesystem root**, they will enumerate the same files.

For large datasets, it is usually preferable to **partition storage across multiple assets**.

Example:

```

/data/shard1
/data/shard2
/data/shard3

```

Each connector instance scans a different root directory.

See:

➡️ [Performance & Throughput](../../concepts/performance.md)

---

## Next Steps

Deploy the connector using one of the supported platforms:

- [Docker Deployment](../../deployment/docker/filesystem.md)
- [Kubernetes Deployment](../../deployment/kubernetes/filesystem.md)
```

