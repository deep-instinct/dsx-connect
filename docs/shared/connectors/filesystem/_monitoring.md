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

