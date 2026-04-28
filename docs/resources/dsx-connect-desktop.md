# DSX-Connect Desktop

DSX-Connect Desktop is the local desktop launcher for DSX-Connect Core and desktop-managed connectors. It runs the DSX-Connect web UI in an Electron shell and manages connector processes on the workstation.

- [DSX-Connect Desktop Releases](https://github.com/deep-instinct/dsx-connect/releases?q=dsx-connect-desktop&expanded=true)

## What It Runs

Desktop starts a local DSX-Connect Core process and opens the UI at:

```text
http://127.0.0.1:8586/
```

Desktop-managed state is stored under:

```text
~/.dsx-connect-local/
```

The desktop launcher state is stored under:

```text
~/.dsx-connect-local/dsx-connect-desktop/
```

Connector launch state is stored in:

```text
~/.dsx-connect-local/dsx-connect-desktop/launcher/launched-connectors.json
```

## Supported Connectors

The desktop launcher can start and manage local connector instances for:

- Filesystem
- AWS S3
- Azure Blob Storage
- Google Cloud Storage
- SharePoint
- OneDrive
- M365 Mail
- Salesforce

## Quick Start

### 1. Install and Open

Download the desktop build from the release page, install it for your operating system, and open DSX-Connect Desktop.

If you are using an unsigned or unnotarized internal macOS build, macOS may block the app on first open with a message like:

```text
"DSX-Connect Desktop.app" Not Opened. Apple could not verify "DSX-Connect Desktop.app" is free of malware that may harm your Mac or compromise your privacy.
```

First try opening it from Finder with right-click, then **Open**. If you already copied the app to `/Applications` and macOS still refuses to open it, remove the quarantine attribute:

```bash
xattr -dr com.apple.quarantine "/Applications/DSX-Connect Desktop.app"
```

For normal end-user distribution, the app should be signed and notarized.

### 2. Install Local Runtime Prerequisites

DSX-Connect Desktop currently requires a local Python runtime with the DSX-Connect Python dependencies and a local Redis server binary. Python and Redis are not fully bundled in the Desktop app yet.

For internal test builds, use the project virtual environment when running from the repository, or set a Python interpreter explicitly:

```bash
export DSXCONNECT_LOCAL_PYTHON=/path/to/python
```

If Python is installed outside the GUI app PATH, Desktop checks common macOS Python locations such as `/usr/local/bin/python3` and `/Library/Frameworks/Python.framework/Versions/Current/bin/python3`.

On macOS, install Redis with Homebrew:

```bash
brew install redis
```

Desktop checks common Homebrew and MacPorts locations, but you can also set the Redis binary path explicitly:

```bash
export DSXCONNECT_LOCAL_REDIS_SERVER=/opt/homebrew/bin/redis-server
```

If you launch Desktop from Finder or `/Applications`, remember that the app may not inherit your shell PATH. Setting `DSXCONNECT_LOCAL_REDIS_SERVER` or installing Redis in a standard Homebrew location avoids that issue.

On Linux, install Redis from your package manager:

```bash
# Debian / Ubuntu
sudo apt-get update
sudo apt-get install redis-server

# RHEL / Fedora
sudo dnf install redis
```

If Redis is installed outside your PATH, set:

```bash
export DSXCONNECT_LOCAL_REDIS_SERVER=/usr/bin/redis-server
```

On Windows, Redis is not distributed as an official native Windows server by the Redis project. Use one of these options:

- Install Redis inside WSL2 and run DSX-Connect Desktop from an environment that can use that `redis-server` binary.
- Use a Windows-compatible Redis distribution such as Memurai for local testing.
- Use Docker Desktop to run Redis and configure DSX-Connect to point at that Redis instance if you are using an external Redis mode.

If you install a Windows-compatible `redis-server.exe`, set the full path before launching Desktop:

```powershell
$env:DSXCONNECT_LOCAL_REDIS_SERVER = "C:\Program Files\Redis\redis-server.exe"
```

### 3. Launch a Connector

Use **Connector > Launch** and choose the connector type.

If the connector has no meaningful saved configuration yet, Desktop opens the configuration dialog. If configuration already exists, Desktop starts the connector without forcing the dialog open.

### 4. Configure Connection Settings

Open a connector's settings dialog from the connector card. The dialog groups settings by:

- Connection
- Policy
- Monitoring
- Runtime and diagnostics

Use **Save Configuration** after editing values. Edits are staged until they are saved.

### 5. Preview and Scan

Use **Show Preview** to validate that the connector can enumerate content before running a full scan.

Use **Sample Scan** for a small end-to-end scan test. Use a full scan only after preview and sample scan behavior look correct.

## Credential Storage

Desktop stores connector-local configuration in `.env.local` files under `~/.dsx-connect-local/`. Connector secrets entered in the UI may be written to these files.

Examples:

```text
~/.dsx-connect-local/aws-s3-connector-desktop/.env.local
~/.dsx-connect-local/azure-blob-storage-connector-desktop/.env.local
~/.dsx-connect-local/google-cloud-storage-connector-desktop/.env.local
~/.dsx-connect-local/sharepoint-connector-desktop/.env.local
~/.dsx-connect-local/onedrive-connector-desktop/.env.local
~/.dsx-connect-local/m365-mail-connector-desktop/.env.local
~/.dsx-connect-local/salesforce-connector-desktop/.env.local
```

Treat these files as sensitive. Do not commit them, share them, or include them in support bundles unless secrets have been removed.

## Reusing Local Provider Credentials

Some providers have useful local credential stores, but not all connectors can safely or consistently reuse them.

### AWS S3

AWS has a standard local credential chain. The AWS SDK can use:

- `~/.aws/credentials`
- `~/.aws/config`
- `AWS_PROFILE`
- `AWS_DEFAULT_REGION`
- SSO/session caches under `~/.aws/sso/cache`
- inherited `AWS_*` environment variables

When possible, prefer using an AWS profile instead of copying `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` into the connector `.env.local` file.

### Google Cloud Storage

Google Cloud clients can use a service-account JSON file via `GOOGLE_APPLICATION_CREDENTIALS`. Desktop lets you select this JSON file and stores the selected path.

Google Application Default Credentials may also exist at:

```text
~/.config/gcloud/application_default_credentials.json
```

For Desktop, prefer storing a path to the intended credentials file rather than copying the JSON content into `.env.local`.

### Azure Blob Storage

The Azure Blob connector currently uses explicit storage credentials such as:

- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_STORAGE_ACCOUNT_NAME`
- `AZURE_STORAGE_ACCOUNT_KEY`

Azure CLI credentials under `~/.azure/` are not a drop-in replacement unless the connector is configured to use Azure Identity credential flow.

### Microsoft Graph Connectors

SharePoint, OneDrive, and M365 Mail use Microsoft Entra app registration values:

- Tenant ID
- Client ID
- Client secret
- Connector-specific target settings

There is no general local credential file equivalent that Desktop should scrape automatically.

### Salesforce

Salesforce Desktop configuration uses explicit Salesforce credentials and settings. Desktop should not scan local files for Salesforce secrets automatically.

## Monitoring

Monitoring enables on-access scanning for new or updated content where the connector supports it.

Filesystem monitoring uses local filesystem watcher settings.

Google Cloud Storage monitoring uses Pub/Sub subscription settings. Changes to monitoring settings may require a connector restart.

SharePoint, OneDrive, and M365 Mail monitoring use Microsoft Graph webhooks. Microsoft Graph must be able to reach the connector callback over public HTTPS. For local demos, Desktop can start a tunnel helper when a supported tool such as `ngrok` or `cloudflared` is available.

Starting a tunnel exposes the local connector callback as a publicly reachable URL. Use it only for demos or controlled testing, and stop the connector or disable monitoring when finished.

## Files and Logs

Desktop-managed connector files are under:

```text
~/.dsx-connect-local/<connector-name>-desktop/
```

Core Desktop files are under:

```text
~/.dsx-connect-local/dsx-connect-desktop/
```

Logs are stored under each connector's local state directory.

## Uninstall and Secret Cleanup

Removing the Desktop app does not automatically remove connector state or secrets from `~/.dsx-connect-local/`.

Before deleting local state, stop DSX-Connect Desktop and any running connector processes.

Review and remove any connector `.env.local` files that still contain secrets:

```bash
find ~/.dsx-connect-local -path '*connector-desktop/.env.local' -print
```

If you want to remove all Desktop-managed connector configuration, remove the connector desktop state directories:

```bash
find ~/.dsx-connect-local -maxdepth 1 -type d -name '*connector-desktop' -print
```

After reviewing the output, delete only the directories you no longer need.

To remove the Desktop launcher state:

```bash
rm -rf ~/.dsx-connect-local/dsx-connect-desktop
```

Do not delete shared provider credential stores such as `~/.aws/`, `~/.config/gcloud/`, or `~/.azure/` unless you intentionally want to remove those provider credentials from the workstation.

## Troubleshooting

If a connector starts but cannot preview or scan content:

- Confirm the asset value points to an accessible bucket, folder, mailbox, site, or object path.
- Confirm the credential values or local credential profile can list and read the target content.
- Check the connector log under `~/.dsx-connect-local/<connector-name>-desktop/`.
- Use **Show Preview** before full scan to separate enumeration failures from scan-processing failures.
- For webhook monitoring, confirm the public callback URL is HTTPS and reachable from the provider.
