# Developer Tasks (Invoke)

This document outlines common development and release automation tasks using Invoke.

This repo uses Invoke for build and release automation. The default collection lives in `tasks.py` and focuses on packaging, releasing, and Helm operations.

## Prerequisites
- Python 3.12+
- `pip install invoke`
- `Docker` (for container builds and Helm packaging pipelines)

## Listing Tasks
```bash
invoke -l                     # default collection (tasks.py)
```

## Adding a New Connector to the Release Pipeline

1. Add a new entry to `CONNECTORS_CONFIG` in `tasks.py` (located at the project root) with the name of the connector folder, which should be in `connectors/<connector_name>` relative to the project root.

```python
# ---------- Edit me ----------
# Explicit, human-edited list of connectors (folder names under ./connectors)
# Flip enabled=True/False or add/remove lines as you like.
CONNECTORS_CONFIG = [
{"name": "aws_s3", "enabled": True},
{"name": "azure_blob_storage", "enabled": True},
{"name": "filesystem", "enabled": True},
{"name": "google_cloud_storage", "enabled": True},
{"name": "sharepoint", "enabled": True}
]
```

## Common Commands

- Release dsx-connect and all connectors - this will bump the versions of all components and push images to `Docker Hub` (requires local running docker, e.g. `docker desktop`, `colima`, etc...):
```bash
invoke release-all
```

- Bundles all docker compose files for the latest release into dist/   The resulting "bundle" can be distributed to users for deployment.  This is often used after a release-all.
```bash
invoke bundle 
```

- Release a connector image with a version bump:
```bash
invoke release-connector --name=aws_s3
```

- Release a connector image without version bump:
```bash
invoke release-connector-nobump --name=aws_s3
```

- Helm release (core + all enabled connectors):
```bash
invoke helm-release --repo=oci://registry-1.docker.io/dsxconnect
```

- Helm release only specific connectors:
```bash
invoke helm-release --only=azure_blob_storage,filesystem
```

- Generate versions manifest:
```bash
invoke generate-manifest
```

## Notes
- Test tasks are not in this file; see `DEVELOPER_TEST_TASKS.md` for auth smoke tests and local run helpers.
- Container bases use `python:3.12-slim-bookworm` and refresh `OpenSSL` packages during build for `CVE` coverage.

