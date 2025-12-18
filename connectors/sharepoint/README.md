<!-- Developer documentation for the SharePoint Connector (not included in release bundles) -->
# Sharepoint Connector Implementation Guide

This project implements a DSX Connector based on the DSX Connector framework.  This README is a guide for how to
implement, debug and create releases.

Documenation for deploying a release should be in file: deploy/README.md will

## Development
Implement the following in `sharepoint_connector.py`:
- **Startup/Shutdown:** Initialize and clean up resources.

and the following API endpoints as applicable:
- **full_scan:** Request for full repository scan.
- **item_action:** Execute remediation actions on a file.
- **read_file:** Request to retrieve file contents.
- **repo_check:** Request that the connector checks its connectivity to its repository
- **webhook_event:** Process external webhook events.

## Running/Testing in an IDE/Debugger
All connectors can be run from the command-line or via an IDE/Debugger.  In this directory, there is both a start.py
file and `sharepoint_connector.py` script either of which can be use to start the connector.

When running this way, the config.py file is read to configure the app, and any one of settings can be
overridden with environment settings.

You should see output similar to this:
```shell
2025-05-21 13:36:15,001 INFO     logging.py          : Log level set to DEBUG
INFO:     Started server process [81998]
INFO:     Waiting for application startup.
2025-05-21 13:36:15,723 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
2025-05-21 13:36:15,723 INFO     sharepoint_connector.py: Starting up connector sharepoint
2025-05-21 13:36:15,723 INFO     sharepoint_connector.py: sharepoint-connector version: 0.1.0.
...
2025-05-21 13:36:15,733 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
INFO:     Application startup complete.
...
```

### Changing Configuration (dev)

Leave `config.py` alone — it contains sane defaults. During development, override via:

- `.dev.env` file next to `config.py` (not included in releases)
  - Example:
    - `DSXCONNECTOR_USE_TLS=false`
    - `DSXCONNECTOR_TLS_CERTFILE=../framework/deploy/certs/dev.localhost.crt`
    - `DSXCONNECTOR_TLS_KEYFILE=../framework/deploy/certs/dev.localhost.key`
    - `DSXCONNECTOR_CONNECTOR_URL=https://sharepoint-connector:8620`
    - `DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586`
    - `DSXCONNECTOR_VERIFY_TLS=false`
    - `DSXCONNECTOR_SP_TENANT_ID=...`
    - `DSXCONNECTOR_SP_CLIENT_ID=...`
    - `DSXCONNECTOR_SP_CLIENT_SECRET=...`
    - `DSXCONNECTOR_SP_HOSTNAME=contoso.sharepoint.com`
    - `DSXCONNECTOR_SP_SITE_PATH=MySite`
    - `DSXCONNECTOR_SP_DRIVE_NAME=Documents`
  - Or set `DSXCONNECTOR_ENV_FILE=/path/to/custom.env` to use a different file.

- Environment variables (shell/Compose/CI)
  - Any setting can be overridden as `DSXCONNECTOR_<SETTING_NAME>`.



## Build a Deployment Release

Connectors use Invoke to manage tasks for bundling up files, creating requirements (for pip) and
building a Docker image.  All the steps needed to prepare a new release for deployment.

### Release Builds

```bash
pip install invoke
invoke release   # clean + build wheel + docker build (auto-bumps patch/build number)
```

Artifacts land in `dist/`. The patch/build increments automatically during `release`; edit `version.py` manually before tagging if you need a major/minor bump.

### Configuration

- Required env vars (can be set via `.env` or compose):
  - `DSXCONNECTOR_SP_TENANT_ID`: Azure AD Tenant ID
  - `DSXCONNECTOR_SP_CLIENT_ID`: App (client) ID
  - `DSXCONNECTOR_SP_CLIENT_SECRET`: App client secret
  - `DSXCONNECTOR_ASSET`: SharePoint URL to the library or folder to scan (see below)
  - Optional (auto‑derived from ASSET if omitted):
    - `DSXCONNECTOR_SP_HOSTNAME`: e.g., `contoso.sharepoint.com`
    - `DSXCONNECTOR_SP_SITE_PATH`: e.g., `MySite`
  - Optional: `DSXCONNECTOR_SP_DRIVE_NAME`
  - TLS: `DSXCONNECTOR_SP_VERIFY_TLS=true|false`, `DSXCONNECTOR_SP_CA_BUNDLE=/path/to/ca.pem`

`connectors/sharepoint/.env.example` contains a ready-to-copy template.

#### Asset + Filter (recommended)
- `DSXCONNECTOR_ASSET`: Paste the full SharePoint URL for the library or folder you want as the scan root.
  - Examples:
    - Library root: `https://<host>/sites/<SiteName>/Shared%20Documents`
    - Folder: `https://<host>/sites/<SiteName>/Shared%20Documents/dsx-connect/scantest`
- `DSXCONNECTOR_FILTER` (optional, rsync-like): include/exclude patterns to control which files are scanned under the above asset.
  - General concepts:
    - a '?' matches any single character except a slash (/).
    - a '*' matches zero or more non-slash characters.
    - a '**' matches zero or more characters, including slashes.
    - '-' or '--exclude' means: exclude the following match
    - no prefix, or '+' or '--include' means: include the following match
    - For a comprehensive guide on rsync filters: rsync filter rules
  - Examples (all filters branch off of DSXCONNECTOR_ASSET):
    | DSXCONNECTOR_FILTER                                   | Description                                                                                                                             |
    |-------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
    | ""                                                    | All files in tree and subtrees (no filter)                                                                                              |
    | "*"                                                   | Only top-level files (no recursion)                                                                                                     |
    | "sub1"                                                | Files within subtree 'sub1' and recurse into its subtrees                                                                               |
    | "sub1/*"                                              | Files within subtree 'sub1', not including subtrees.                                                                                    |
    | "sub1/sub2"                                           | Files within subtree 'sub1/sub2', recurse into subtrees.                                                                                |
    | "*.zip,*.docx"                                        | All files with .zip and .docx extensions anywhere in the tree                                                                           |
    | "-tmp --exclude cache"                                | Exclude noisy directories (tmp, cache) but include everything else                                                                      |
    | "sub1 -tmp --exclude sub2"                            | Combine includes and excludes - scan under 'sub1' subtree, but skip 'tmp' or 'sub2' subtrees                                           |
    | "test/2025*/*"                                        | All files in subtrees matching 'test/2025*/*'. Does not recurse.                                                                        |
    | "test/2025*/** -sub2"                                 | All files in subtrees matching 'test/2025*/*' and recursively down. Skips any subtree 'sub2'.                                          |
    | "'scan here' -'not here' --exclude 'not here either'" | Quoted tokens (spaces in dir names)                                                                                                     |

Behavior
- On startup, the connector parses `DSXCONNECTOR_ASSET` once and derives:
  - `SP_HOSTNAME`, `SP_SITE_PATH` (if omitted in env), and a resolved base path inside the drive.
  - If ASSET host/site differ from explicitly configured values, a warning is logged and the configured values are used.
- Full scan uses the resolved base path directly (no runtime parsing) and enqueues scan requests by item ID.
- read_file and item_action receive the same item IDs back from dsx-connect and do not need the original URL context.

Notes
- “Documents” and “Shared Documents” are treated as the same default library when resolving drives.
- You can still set `DSXCONNECTOR_SP_DRIVE_NAME` to target a specific document library; avoid putting folders in this field.

#### Permissions (Microsoft Entra ID → Microsoft Graph Application)
- Read/list/download: `Files.Read.All` or `Sites.Read.All` (admin consent)
- Write (create/upload/move/delete): `Files.ReadWrite.All` or `Sites.ReadWrite.All` (admin consent)
- Least privilege alternative: `Sites.Selected` plus a per‑site grant with role `read` or `write` via Graph:
  - Get site id: `GET https://graph.microsoft.com/v1.0/sites/{hostname}:/sites/{sitePath}`
  - Grant: `POST https://graph.microsoft.com/v1.0/sites/{siteId}/permissions/grant`
    - Body: `{ "recipients": [{ "appId": "<client-id>" }], "roles": ["read"] }` or `["write"]`

### Handlers

This connector implements handlers via `DSXConnector`:

- `full_scan`: Enumerates files in the configured SharePoint drive and applies DSXCONNECTOR_FILTER before enqueuing scan requests (location=item-id).
- `read_file`: Streams file content via Microsoft Graph `/drives/{drive}/items/{id}/content`.
- `item_action`: Supports `DELETE` (removes item by id). Other actions return NOT_IMPLEMENTED.
- `repo_check`: Validates connectivity by resolving site/drive and listing root.

Handler semantics with ASSET URLs
- full_scan accepts `DSXCONNECTOR_ASSET` as a full SharePoint URL; the connector resolves the URL to a drive subpath at startup.
- full_scan enqueues scan requests using item IDs; read_file and item_action therefore operate on IDs without needing to re-parse URLs.

### Compose

The compose file under `deploy/` includes the SP_* envs and TLS toggles. Provide values via a `.env` file or your environment.
Local running Docker instance: if building a Docker image (a "release")

Ideally, also a remote docker hub instance that you can push the image to.  This can be configured in the tasks.py file by setting the following:
repo_uname = "<your repo>"

### Using invoke
```python
pip install invoke
```
Navigate to the root directory (where the tasks.py file resides) and use invoke cli to run tasks
```python
invoke release
```
* Files will be bundled up in the dist folder.
* If docker is running locally, a docker image will be built.
* If access to a docker repository is given, the docker image will be pushed to that repository
* Docker images tagged with sharepoint-connector:<version> and sharepoint-connector:latest

Other invoke options:
* bump - increments the patch version in version.py (e.g., 1.0.0 to 1.0.1).
* clean - removes the distribution folder (dist/sharepoint-connector-<version>) and its associated zip file if they exist.
* prepare - prepares files for a versioned build.  Copies and moves file into dist/sharepoint-connector-<version>; generates requirements.txt.
* build - (runs bump, clean, prepare) and builds a Docker image tagged as sharepoint-connector:<version> from the prepared dist folder if it doesn’t already exist.
* push - (runs build) tags the Docker image with the repository username (dsxconnect/<name>:<version>) and pushes it to Docker Hub.
* release - executes the full release cycle by running the following tasks in order: bump, clean, prepare, build, and push.
