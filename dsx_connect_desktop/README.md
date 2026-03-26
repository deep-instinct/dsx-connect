# DSX-Connect Desktop (Electron)

Electron shell for the existing DSX Connect web UI.

## What it does

- Starts local DSX Connect core via `dsx_connect/local/dsx_connect_local.py start`
- Waits for `http://127.0.0.1:8586/`
- Loads the existing DSX Connect UI in an Electron window
- Optional stop-on-exit: set `DSXCONNECT_STOP_ON_EXIT=1`

## Run (dev)

```bash
cd dsx_connect_desktop
npm install
npm start
```

## Notes

- It uses your repo's Python environment when available (`.venv/bin/python` first).
- This launcher hosts the existing UI and does not duplicate frontend code.
- Connector processes (filesystem/sharepoint) are still launched separately unless you add orchestration.
