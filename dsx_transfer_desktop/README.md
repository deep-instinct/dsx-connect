# DSX-Transfer Desktop

DSX-Transfer Desktop is an Electron shell for running guarded file-share transfers with the existing `dsx_transfer` Python engine.

The first demo flow copies files from a source folder or mounted file share to a destination folder only after the scanner and transfer policy return an allow decision.

## Run From Source

From the repository root:

```bash
cd dsx_transfer_desktop
npm install
npm run dev
```

The desktop app expects a Python runtime that can import `dsx_transfer`. In this repo it automatically tries `../.venv/bin/python` on macOS/Linux and `..\\.venv\\Scripts\\python.exe` on Windows. You can override that with:

```bash
DSX_TRANSFER_DESKTOP_PYTHON=/path/to/python npm run dev
```

## Build Installers

```bash
cd dsx_transfer_desktop
npm run build:mac
npm run build:win
```

This initial desktop package bundles the `dsx_transfer` and `dsxa_sdk_py` source trees as app resources, but it still uses an available Python runtime. A later packaging pass should embed a signed Python runtime per platform for a fully self-contained `.app` and `.exe`.

## Demo Flow

- DSXA scanner: sends file streams through DSXA before commit.
- Verdict actions: benign, malicious, unknown, and error decisions can be mapped to allow or block.
- File-share transfer: source and destination are local folders or mounted shares.

Each run writes a generated `dsx-transfer.yaml`, audit JSONL, and checkpoint file under the app user-data directory.
