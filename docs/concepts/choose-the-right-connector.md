# Choosing the Right Connector

The correct DSX-Connect connector is determined by **how your files are hosted and accessed**.

Do not start by asking “Which connector should I use?”

Start by asking:

> How are your files stored today?

---

## Step 1: Identify the Storage Model

Most enterprise file repositories fall into one of three categories.

---

### 1️⃣ Object Storage (API-Based)

Examples:

- Amazon S3
- Azure Blob Storage
- Google Cloud Storage

Characteristics:

- Accessed via REST API
- Cloud-native
- Horizontally scalable
- No mounted storage required

**Use the corresponding object storage connector.**

These connectors communicate directly with the storage provider API.

---

### 2️⃣ Network-Served Filesystems

Examples:

- NFS
- SMB / CIFS
- NAS appliances (NetApp, Isilon)
- Azure Files
- AWS EFS
- CephFS
- Enterprise file shares

These systems:

- Serve files over the network
- Support multiple clients
- Act as centralized storage services

Even though they are “filesystems,” they behave like storage services.

**Use the Filesystem connector.**

Deployment pattern:

- Docker → Mount on host, then bind-mount into container
- Kubernetes → Mount via PersistentVolumeClaim (RWX recommended)

This is the most common enterprise filesystem use case.

---

### 3️⃣ Node-Local Storage (Edge / Single Server)

Examples:

- `/mnt/data` on a server
- Local desktop folders
- Edge devices

Characteristics:

- Not centrally served
- Bound to a specific machine
- Not inherently horizontally scalable

**Use the Filesystem connector.**

However:

- Docker Compose is often simpler than Kubernetes for node-local storage.
- In Kubernetes, `hostPath` ties the connector to a node.

This pattern is best suited for:

- Edge deployments
- Single-node clusters
- Development environments

---

## Architectural Summary

| Storage Type | Recommended Connector | Notes |
|--------------|----------------------|-------|
| Object Storage | S3 / Azure / GCS connector | Cloud-native, API-driven |
| Networked Filesystem | Filesystem connector | Mount via PVC or bind mount |
| Node-Local Disk | Filesystem connector | Edge / dev only |

---

## Key Insight

The Filesystem connector is not a special-case connector.

The storage backend determines:

- Portability
- Scheduling behavior (Kubernetes)
- Scalability
- Deployment complexity

In production Kubernetes environments, network-backed storage is recommended.

---

## When in Doubt

If your storage is accessed by multiple systems over the network, it is almost always a **served storage system**, and the Filesystem connector should be deployed using PVC-backed storage.