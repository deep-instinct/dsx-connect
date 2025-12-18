<!-- Developer documentation for the Azure Blob Storage Connector (not included in release bundles) -->
# Azure Blob Storage Connector Implementation Guide

This project implements a DSX Connector based on the DSX Connector framework.  This README is a guide for how to
implement, debug and create releases.

Documenation for deploying a release should be in file: deploy/README.md will


## Development
Implement the following in `azure_blob_storage_connector.py`:
- **Startup/Shutdown:** Initialize and clean up resources.

and the following API endpoints as applicable:
- **full_scan:** Request for full repository scan.
- **item_action:** Execute remediation actions on a file.
- **read_file:** Request to retrieve file contents.
- **repo_check:** Request that the connector checks its connectivity to its repository
- **webhook_event:** Process external webhook events.

### Running/Testing in an IDE/Debugger
All connectors can be run from the command-line or via an IDE/Debugger.  In this directory, there is both a start.py
file and `azure_blob_storage_connector.py` script either of which can be run.

When running this way, the config.py file is read to configure the app, and any one of settings can be
overridden with environment settings.

You should see output similar to this:
```shell
2025-05-21 13:36:15,001 INFO     logging.py          : Log level set to DEBUG
INFO:     Started server process [81998]
INFO:     Waiting for application startup.
2025-05-21 13:36:15,723 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
2025-05-21 13:36:15,723 INFO     azure_blob_storage_connector.py: Starting up connector google-cloud-storage-connector-9788
2025-05-21 13:36:15,723 INFO     azure_blob_storage_connector.py: azure-blob-storage-connector-9788 version: 0.1.0.
2025-05-21 13:36:15,724 INFO     azure_blob_storage_connector.py: azure-blob-storage-connector configuration loaded.
2025-05-21 13:36:15,724 INFO     azure_blob_storage_connector.py: azure-blob-storage-connector:azure-blob-storage-connector-9788 startup completed.
2025-05-21 13:36:15,733 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8595 (Press CTRL+C to quit)
```


#### Azure Connection String
In order to access Azure Blob Storage, this connector currently uses connection strings.  To get a connection string:
From Azure Portal
1. Go to Azure Portal.
2. Navigate to your Storage Account.
3. In the left-hand menu, click Access keys (under "Security + networking").
   * You'll see two key sets. Under either one:
     * Click Show keys.
     * Copy the Connection string (starts with DefaultEndpointsProtocol=https;...).

You will then either need to store this connection string as an environment setting, or pass it as an environment
setting when running the connector:
```shell
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
```
or
```shell
AZURE_STORAGE_CONNECTION_STRING="..." python start.py
```
#### Changing Configuration (dev)

Leave `config.py` alone — it contains sane defaults. During development, override via:

- `.devenv` file next to `config.py` (not included in releases)
  - Example:
    - `DSXCONNECTOR_USE_TLS=false`
    - `DSXCONNECTOR_TLS_CERTFILE=../framework/deploy/certs/dev.localhost.crt`
    - `DSXCONNECTOR_TLS_KEYFILE=../framework/deploy/certs/dev.localhost.key`
    - `DSXCONNECTOR_CONNECTOR_URL=https://azure-blob-storage-connector:8599`
    - `DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586`
    - `DSXCONNECTOR_VERIFY_TLS=false`
    - `DSXCONNECTOR_ASSET=container-name`
    - `DSXCONNECTOR_FILTER=`
  - Or set `DSXCONNECTOR_ENV_FILE=/path/to/custom.env` to use a different file.

- Environment variables (shell/Compose/CI)
  - Any setting can be overridden as `DSXCONNECTOR_<SETTING_NAME>`.


## Build a Deployment Release

Connectors use Invoke to manage tasks for bundling up files, creating requirements (for pip) and
building a Docker image.  All the steps needed to prepare a new release for deployment.

#### Prerequisites
Local running Docker instance: if building a Docker image (a "release")

#### Using invoke
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
* Docker images tagged with {{ cookiecutter.__release_name }}:<version> and {{ cookiecutter.__release_name }}:latest

Other invoke options:
* bump - increments the patch version in version.py (e.g., 1.0.0 to 1.0.1). Use this for major/minor changes before tagging if required.
* clean - removes the distribution folder (dist/azure-blob-storage-connector-<version>) and its associated zip file if they exist.
* prepare - prepares files for a versioned build.  Copies and moves file into dist/azure-blob-storage-connector-<version>; generates requirements.txt.
* build - (runs bump, clean, prepare) and builds a Docker image tagged as azure-blob-storage-connector:<version> from the prepared dist folder if it doesn’t already exist.
* push - (runs build) tags the Docker image with the repository username (logangilbert/<name>:<version>) and pushes it to Docker Hub.
* release - executes the full release cycle by running the following tasks in order: bump, clean, prepare, build, and push. The patch/build number increments automatically; edit version.py manually for major/minor bumps before running release.

## Filtering (DSXCONNECTOR_FILTER)

The Azure Blob connector supports rsync-like include/exclude patterns to control which blobs are scanned. Leave empty ("") to scan all blobs under DSXCONNECTOR_ASSET (the container).

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

Implementation notes:
- The connector uses provider-side prefix narrowing when safe, and always verifies with the same rsync-like rules for correctness.
