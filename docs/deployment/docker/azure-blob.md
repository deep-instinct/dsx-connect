# Azure Blob Storage Connector — Docker Compose

This guide shows how to deploy the Azure Blob connector with Docker Compose for quick testing/POV.

## Prerequisites
- Docker installed locally (or a container VM)
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Examples below assume the extracted folder is `dsx-connect-<core_version>/`. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- Azure Storage credentials with permissions to list/read (and optionally write/move/delete) blobs:
  - Connection string (recommended for POV) or SAS/Managed Identity as applicable
- A Docker network shared with dsx‑connect (example: `dsx-connect-network`)

## Compose File
In the extracted bundle, use `dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/docker-compose-azure-blob-storage-connector.yaml`.

### Core connector env (common across connectors)

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_DSX_CONNECT_URL` | dsx‑connect base URL (use `http://dsx-connect-api:8586` on the shared Docker network). |
| `DSXCONNECTOR_CONNECTOR_URL` | Callback URL dsx-connect uses to reach the connector (defaults to the service name inside the Docker network). |
| `DSXCONNECTOR_ASSET` | Container or `container/prefix` to scope listings. |
| `DSXCONNECTOR_FILTER` | Optional rsync‑style include/exclude rules relative to the asset. |
| `DSXCONNECTOR_ITEM_ACTION` | What to do on malicious verdicts (`nothing`, `delete`, `move`, `move_tag`). Use `move`/`move_tag` to relocate blobs after verdict. |
| `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Destination container/prefix for moved blobs when using `move`/`move_tag`. |

### Azure-specific settings

| Variable | Description |
| --- | --- |
| `AZURE_STORAGE_CONNECTION_STRING` | Connection string for the storage account (store via secrets). |

Copy the sample env file and edit it:
```bash
cp dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/.sample.azure-blob.env \
  dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/.env
# edit dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/.env (AZURE_STORAGE_CONNECTION_STRING, DSXCONNECTOR_ASSET, etc.)
```

Deploy:
```bash
docker compose --env-file dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/azure-blob-storage-connector-<connector_version>/docker-compose-azure-blob-storage-connector.yaml up -d
```

## Assets and Filters
- `DSXCONNECTOR_ASSET` should be set to your container (e.g., `my-container`) or `container/prefix` to scope listings.
- If a prefix is provided, listings start at that sub‑root and filters are evaluated relative to it.
- See Reference → [Assets & Filters](../../reference/assets-and-filters.md) for sharding/partition guidance.

## Notes
- Provide `AZURE_STORAGE_CONNECTION_STRING` (or other supported auth env) via secrets for security.

## TLS Options
See [Deploying with SSL/TLS](./tls.md) for Docker Compose examples (core + connectors), including runtime-mounted certs and local-dev self-signed cert generation.

## Webhook Exposure
If you expose connector endpoints (e.g., for HTTP callbacks) outside Docker, tunnel or publish the host port mapped to `8610` (compose default). Keep `DSXCONNECTOR_CONNECTOR_URL` pointing to the Docker-network address (e.g., `http://azure-blob-storage-connector:8610`) so dsx-connect can reach the service internally.

## Provider Notes (Azure Blob)
- Auth: connection string works well for POV; SAS or managed identity might be used in production.
- HNS (ADLS Gen2): hierarchical namespace affects path semantics; test your prefixes under HNS.
- Listing costs: large containers can incur list costs; sharding by asset improves performance.
- SAS Expiry: ensure long enough validity for ongoing scans.
