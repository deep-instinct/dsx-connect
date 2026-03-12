# DSX-Connect Local Runtime

## Local Runtime Manager (macOS MVP)

Run DSX-Connect core + workers + Redis locally (no Docker/K8s):

```bash
# 1) create local state + env template
python3 dsx_connect/local/dsx_connect_local.py init

# 2) edit ~/.dsx-connect-local/.env.local (scanner URL/token, auth, dianna)

# 3) start stack
python3 dsx_connect/local/dsx_connect_local.py start

# check status
python3 dsx_connect/local/dsx_connect_local.py status

# tail logs
python3 dsx_connect/local/dsx_connect_local.py logs api --lines 100
python3 dsx_connect/local/dsx_connect_local.py logs workers --lines 100
python3 dsx_connect/local/dsx_connect_local.py logs redis --lines 100

# stop stack
python3 dsx_connect/local/dsx_connect_local.py stop
```

Notes:
- Requires `redis-server` in `PATH` (`brew install redis` on macOS).
- Default runtime dir: `~/.dsx-connect-local`.
- Default Redis port for local runtime: `6380`.

## Native Binaries (Nuitka, macOS MVP)

Build local runtime CLIs into native binaries:

```bash
# from repo root, using your active venv
pip install nuitka
python3 dsx_connect/local/build_local_binaries.py build all

# macOS .app bundles
python3 dsx_connect/local/build_local_binaries.py build-app all
```

Output defaults to `dist/local-binaries` and includes:
- `dsx_connect_local` (core local manager)
- `filesystem_local` (filesystem connector local manager)

Run binaries directly:

```bash
./dist/local-binaries/dsx_connect_local init
./dist/local-binaries/dsx_connect_local start
./dist/local-binaries/filesystem_local init
./dist/local-binaries/filesystem_local start
```


Bundled Redis for demo-friendly app builds:

```bash
# auto-detect redis-server from common macOS paths and bundle into core app
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app core

# or provide an explicit redis-server binary to bundle
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app core \
  --redis-binary /opt/homebrew/bin/redis-server
```

When bundled, the app prefers its internal `redis-server` first, so Finder/double-click launches do not rely on shell PATH.


## Local GUI App (Dock-Friendly)

Build a simple GUI app for demo use (Start/Stop/Status/Logs/Open UI):

```bash
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app core-gui
```

Launch:

```bash
open dist/local-apps/dsx_connect_local_gui.app
```

The GUI app includes bundled `redis-server` by default when available, so it does not depend on Finder PATH.



Filesystem GUI app:

```bash
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app filesystem-gui
open dist/local-apps/filesystem_local_gui.app
```

## macOS Installer (.pkg)

Build a macOS installer package from app bundle(s):

```bash
# Core GUI installer
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-pkg core-gui

# Filesystem GUI installer
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-pkg filesystem-gui

# One installer containing both
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-pkg all
```

Output defaults to `dist/local-pkg/*.pkg` and installs app bundles into `/Applications`.

## Signing + Notarization (GitHub Actions)

The `release-local-apps.yml` workflow supports optional macOS signing/notarization via repo secrets:

- `APPLE_CERT_P12_BASE64`: base64 of exported `.p12` cert bundle
- `APPLE_CERT_PASSWORD`: password used when exporting `.p12`
- `APPLE_CODESIGN_IDENTITY`: e.g. `Developer ID Application: Your Company, Inc. (TEAMID)`
- `APPLE_INSTALLER_IDENTITY`: e.g. `Developer ID Installer: Your Company, Inc. (TEAMID)`
- `APPLE_ID`: Apple ID email
- `APPLE_APP_SPECIFIC_PASSWORD`: app-specific password for Apple ID
- `APPLE_TEAM_ID`: 10-char Apple team ID

If signing/notary secrets are absent, the workflow still builds unsigned artifacts.

SharePoint local manager:

```bash
python3 connectors/sharepoint/local/sharepoint_local.py init
python3 connectors/sharepoint/local/sharepoint_local.py start
python3 connectors/sharepoint/local/sharepoint_local.py status
python3 connectors/sharepoint/local/sharepoint_local.py logs --lines 100
python3 connectors/sharepoint/local/sharepoint_local.py stop
```

SharePoint GUI app:

```bash
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app sharepoint-gui
open dist/local-apps/sharepoint_local_gui.app
```

SharePoint credential setup shortcuts:

```bash
# interactive prompt for tenant/client/secret
python3 connectors/sharepoint/local/sharepoint_local.py init

# non-interactive
python3 connectors/sharepoint/local/sharepoint_local.py init \
  --no-prompt-credentials \
  --tenant-id "<tenant-id>" \
  --client-id "<client-id>" \
  --client-secret "<client-secret>"
```

The SharePoint GUI (`sharepoint_local_gui.app`) also loads/saves these values from:
`~/.dsx-connect-local/sharepoint-connector/.env.local`
via the **Save Config** button.

## Cross-Platform Web Launcher (pywebview)

A single HTML/JavaScript launcher UI for core + connectors:

```bash
pip install pywebview
python3 dsx_connect/local/web_launcher.py
```

Profiles:
- DSX Connect Core
- Filesystem Connector
- SharePoint Connector

For SharePoint, the launcher can save `DSXCONNECTOR_SP_TENANT_ID`,
`DSXCONNECTOR_SP_CLIENT_ID`, and `DSXCONNECTOR_SP_CLIENT_SECRET` into:
`~/.dsx-connect-local/sharepoint-connector/.env.local`


Web launcher app (HTML/JS via pywebview):

```bash
pip install pywebview
./.venv/bin/python dsx_connect/local/build_local_binaries.py build-app web-launcher
open dist/local-apps/web_launcher.app
```
