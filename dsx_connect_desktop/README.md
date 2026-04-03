# DSX-Connect Desktop (Electron)

Electron launcher for the existing DSX-Connect web UI and local runtime.

## What it does

- Starts local DSX-Connect core using [`dsx_connect/local/dsx_connect_local.py`](../dsx_connect/local/dsx_connect_local.py)
- Uses a dedicated desktop state directory under `~/.dsx-connect-local/dsx-connect-desktop`
- Loads the existing DSX-Connect UI in an Electron window at `http://127.0.0.1:8586/`
- Manages selected local connectors from the desktop shell
- Persists launched connector state so desktop-managed connectors can be rehydrated on restart

## Managed connectors

The current launcher knows how to start and manage these local connectors:

- Filesystem
- SharePoint
- AWS S3
- Azure Blob Storage
- Salesforce

Connector launch state is persisted in:

```text
~/.dsx-connect-local/dsx-connect-desktop/launcher/launched-connectors.json
```

## Run (dev)

```bash
cd dsx_connect_desktop
npm install
npm start
```

## Notes

- It uses the repo Python environment when available, preferring `.venv/bin/python` on Unix-like systems.
- This launcher hosts the existing DSX-Connect UI and does not duplicate frontend application code.
- Redis must be available on `PATH` unless you point the local runtime at an explicit Redis binary.
- Connector and core shutdown behavior can be controlled with:
  - `DSXCONNECT_STOP_ON_EXIT`
  - `DSXCONNECT_STOP_CONNECTORS_ON_EXIT`
