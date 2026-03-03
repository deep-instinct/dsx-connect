# Filesystem Connector (Kubernetes)

The Filesystem connector integrates with storage that is accessible as a mounted filesystem.

In Kubernetes, the behavior of this connector is determined entirely by the **storage model backing the volume**.

Before deploying, to understand which storage model is suitable for your environment: [Concepts → Choosing the Right Connector](../../xconcepts/choosing-the-right-connector)

---

## Recommended Pattern: PVC-Backed Storage

In production Kubernetes environments, the Filesystem connector should mount storage via a PersistentVolumeClaim (PVC).

This allows:

- Node-independent scheduling
- Portability across cluster nodes
- Horizontal scalability
- Alignment with Kubernetes storage architecture

In the helm chart for this connector, note the examples/volume-mounts/ directory, which contains examples of how to mount a PVC to NFS, SMB, EFS, etc...
Example:

```yaml
volumeMounts:
  - name: scan-root
    mountPath: /app/scan_folder

volumes:
  - name: scan-root
    persistentVolumeClaim:
      claimName: dsxconnect-scan-pvc
```

### Storage Requirements

For multi-replica deployments, the storage class should support:

* `ReadWriteMany` (RWX)

Examples:

* NFS
* Windows Fileshares (SMB)
* AWS EFS
* Azure Files
* CephFS
* Longhorn (RWX)

When backed by network storage, the Filesystem connector behaves similarly to object storage connectors.

---

## Node-Local Storage (`hostPath`) - i.e. Scan a Local Filesystem

For single-node clusters (k3s, Colima, etc.), you may mount node-local storage using `hostPath`.

Example:

```yaml
volumes:
  - name: scan-root
    hostPath:
      path: /mnt/DESKTOP1/share
      type: Directory
```

### Important

* `hostPath` binds the connector to a specific node.
* Scaling replicas requires identical paths across nodes.
* Scheduling constraints may be required.
* Behavior varies by platform.

This pattern is suitable for:

* Development
* Edge nodes
* Controlled single-node clusters

For purely node-local scanning, Docker Compose may be operationally simpler.

---

## Scaling Considerations

Even with shared RWX storage:

* Multiple replicas scanning the same root will duplicate enumeration.
* Partition large datasets using asset-based sharding.

Example:

* `/data/shard1`
* `/data/shard2`
* `/data/shard3`

Each connector instance should own a distinct root.

See:

[Concepts → Performance & Throughput](../../concepts/performance.md)

---

## Production Guidance

| Environment              | Recommended Storage         |
| ------------------------ | --------------------------- |
| Docker Compose           | Host mount or network share |
| Kubernetes (single node) | hostPath acceptable         |
| Kubernetes (cluster)     | PVC with RWX storage        |

---

## Summary

The Filesystem connector is storage-agnostic.

Operational differences arise from the storage backend:

* Node-local storage introduces scheduling constraints.
* Network-backed storage aligns with Kubernetes architecture.
* The connector model remains consistent across both.

