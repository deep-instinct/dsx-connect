# Salesforce Connector Implementation Guide

This project implements a DSX Connector based on the DSX Connector framework.  This README is a guide for how to
implement, debug and create releases.

## Development
Implement the following in `salesforce_connector.py`:
- **Startup/Shutdown:** Initialize and clean up resources.

and the following API endpoints as applicable:
- **full_scan:** Request for full repository scan.
- **item_action:** Execute remediation actions on a file.
- **read_file:** Request to retrieve file contents.
- **repo_check:** Request that the connector checks its connectivity to its repository
- **webhook_event:** Process external webhook events.

Tip: Set `DSXCONNECTOR_DISPLAY_NAME` to show a friendly name on the dsx-connect UI card without changing the connector slug or routes.

## Running/Testing in an IDE/Debugger
All connectors can be run from the command-line or via an IDE/Debugger.  In this directory, there is both a start.py
file and `salesforce_connector.py` script either of which can be use to start the connector.

When running this way, the config.py file is read to configure the app, and any one of settings can be
overridden with environment settings.

You should see output similar to this:
```shell
2025-05-21 13:36:15,001 INFO     logging.py          : Log level set to DEBUG
INFO:     Started server process [81998]
INFO:     Waiting for application startup.
2025-05-21 13:36:15,723 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
2025-05-21 13:36:15,723 INFO     salesforce_connector.py: Starting up connector salesforce
2025-05-21 13:36:15,723 INFO     salesforce_connector.py: salesforce-connector version: 0.1.0.
...
2025-05-21 13:36:15,733 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
INFO:     Application startup complete.
...
```

### Changing Configuration (dev)

Leave `config.py` alone — it contains sane defaults. During development, override via:

- Use a `.dev.env` file in the same directory. This file is sourced automatically via `shared.dev_env.load_devenv`.
  - Example overrides:
    - `DSXCONNECTOR_USE_TLS=false`
    - `DSXCONNECTOR_TLS_CERTFILE=../framework/deploy/certs/dev.localhost.crt`
    - `DSXCONNECTOR_TLS_KEYFILE=../framework/deploy/certs/dev.localhost.key`
    - `DSXCONNECTOR_CONNECTOR_URL=https://salesforce-connector:8670`
    - `DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586`
    - `DSXCONNECTOR_VERIFY_TLS=false`
    - `DSXCONNECTOR_ASSET=...`
    - `DSXCONNECTOR_FILTER=...`
  - Optionally set `DSXCONNECTOR_ENV_FILE=/path/to/custom.env` to point at another env file.

- Environment variables (shell/Compose/CI)
  - Any setting can be overridden as `DSXCONNECTOR_<SETTING_NAME>`.

### Salesforce authentication & query settings

| Variable | Description |
| --- | --- |
| `DSXCONNECTOR_SF_LOGIN_URL` | OAuth base URL (`https://login.salesforce.com` for production, `https://test.salesforce.com` for sandboxes). |
| `DSXCONNECTOR_SF_API_VERSION` | Salesforce REST API version (e.g., `v60.0`). |
| `DSXCONNECTOR_SF_CLIENT_ID` / `DSXCONNECTOR_SF_CLIENT_SECRET` | Connected App consumer key/secret. |
| `DSXCONNECTOR_SF_USERNAME` / `DSXCONNECTOR_SF_PASSWORD` / `DSXCONNECTOR_SF_SECURITY_TOKEN` | Username-password OAuth credentials (append the security token if required). |
| `DSXCONNECTOR_ASSET` | Optional SOQL clause appended to the ContentVersion query (e.g., `ContentDocumentId = '069xx0000001234AAA'`). |
| `DSXCONNECTOR_SF_WHERE`, `DSXCONNECTOR_SF_FIELDS`, `DSXCONNECTOR_SF_ORDER_BY` | Customize the ContentVersion query fields, filters, and ordering. |
| `DSXCONNECTOR_FILTER` | Comma-separated file extensions to enqueue (e.g., `pdf,docx`). Leave blank to ingest everything returned by the SOQL query. |
| `DSXCONNECTOR_SF_MAX_RECORDS` | Maximum ContentVersion rows queued during a single full scan. |

> **Secrets:** In production, source the Salesforce secrets from Docker/Kubernetes secrets (enrollment tokens, client secret, password) instead of hard-coding them in values files.

Example Kubernetes Secret + Helm reference:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-connector-credentials
type: Opaque
stringData:
  DSXCONNECTOR_SF_CLIENT_ID: "<consumer-key>"
  DSXCONNECTOR_SF_CLIENT_SECRET: "<consumer-secret>"
  DSXCONNECTOR_SF_USERNAME: "user@example.com"
  DSXCONNECTOR_SF_PASSWORD: "<password>"
  DSXCONNECTOR_SF_SECURITY_TOKEN: "<token>"
```

```yaml
# values.yaml
envSecretRefs:
  - salesforce-connector-credentials
```



## Build a Deployment Release

Connectors use Invoke to manage tasks for bundling up files, creating requirements (for pip) and
building a Docker image.  All the steps needed to prepare a new release for deployment.

### Prerequisites
Local running Docker instance: if building a Docker image (a "release")

Ideally, also a remote docker hub instance that you can push the image to.  This can be configured in the tasks.py file by setting the following:
repo_uname = "<your repo>"

### Using invoke
```python
pip install invoke
```
Navigate to the root directory (where the tasks.py file resides) and use invoke cli to run tasks
```python
invoke release   # clean + build wheel + docker build (auto-bumps patch/build number)
```
* Files will be bundled up in the dist folder.
* If docker is running locally, a docker image will be built.
* If access to a docker repository is given, the docker image will be pushed to that repository
* Docker images tagged with salesforce-connector:<version> and salesforce-connector:latest

Other invoke options:
* bump - increments the patch version in version.py (e.g., 1.0.0 to 1.0.1). Use this for manual major/minor bumps before tagging if needed.
* clean - removes the distribution folder (dist/salesforce-connector-<version>) and its associated zip file if they exist.
* prepare - prepares files for a versioned build.  Copies and moves file into dist/salesforce-connector-<version>; generates requirements.txt.
* build - (runs bump, clean, prepare) and builds a Docker image tagged as salesforce-connector:<version> from the prepared dist folder if it doesn’t already exist.
* push - (runs build) tags the Docker image with the repository username (dsxconnect/<name>:<version>) and pushes it to Docker Hub.
* release - executes the full release cycle by running the following tasks in order: bump, clean, prepare, build, and push. The patch/build number increments automatically; edit version.py manually before release if you need to bump major/minor versions.

## Filtering (DSXCONNECTOR_FILTER)

Use rsync-like include/exclude patterns to control which repository items are scanned. Leave empty ("") to scan all under DSXCONNECTOR_ASSET.

General concepts:
- a '?' matches any single character except a slash (/).
- a '*' matches zero or more non-slash characters.
- a '**' matches zero or more characters, including slashes.
- '-' or '--exclude' means: exclude the following match
- no prefix, or '+' or '--include' means: include the following match
- For a comprehensive guide on rsync filters: rsync filter rules

Examples (all filters branch off of DSXCONNECTOR_ASSET):

| DSXCONNECTOR_FILTER                                     | Description                                                                                                                             |
|---------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| ""                                                      | All files in tree and subtrees (no filter)                                                                                              |
| "*"                                                     | Only top-level files (no recursion)                                                                                                     |
| "sub1"                                                  | Files within subtree 'sub1' and recurse into its subtrees                                                                               |
| "sub1/*"                                                | Files within subtree 'sub1', not including subtrees.                                                                                    |
| "sub1/sub2"                                             | Files within subtree 'sub1/sub2', recurse into subtrees.                                                                                |
| "*.zip,*.docx"                                          | All files with .zip and .docx extensions anywhere in the tree                                                                           |
| "-tmp --exclude cache"                                  | Exclude noisy directories (tmp, cache) but include everything else                                                                      |
| "sub1 -tmp --exclude sub2"                              | Combine includes and excludes - scan under 'sub1' subtree, but skip 'tmp' or 'sub2' subtrees                                           |
| "test/2025*/*"                                          | All files in subtrees matching 'test/2025*/*'. Does not recurse.                                                                        |
| "test/2025*/** -sub2"                                   | All files in subtrees matching 'test/2025*/*' and recursively down. Skips any subtree 'sub2'.                                          |
| "'scan here' -'not here' --exclude 'not here either'"   | Quoted tokens (spaces in dir names)                                                                                                     |
