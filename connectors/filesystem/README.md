<!-- Developer documentation for the Filesystem Connector (not included in release bundles) -->
# Filesystem Implementation Guide

This project implements a DSX Connector based on the DSX Connector framework.  This README is a guide for how to
implement, debug and create releases.

Documentation for deploying a release should be in file: deploy/README.md will

## Development
Implement the following in `filesystem_connector.py`:
- **Startup/Shutdown:** Initialize and clean up resources.

and the following API endpoints as applicable:
- **full_scan:** Request for full repository scan.
- **item_action:** Execute remediation actions on a file.
- **read_file:** Request to retrieve file contents.
- **repo_check:** Request that the connector checks its connectivity to its repository
- **webhook_event:** Process external webhook events.

### Monitoring (watchfiles)
- The filesystem connector uses `watchfiles` for directory monitoring (migrated from `watchdog`).
- Benefits: cross‑platform reliability, active maintenance, built‑in debounce, simpler async use.
- Behavior: recursive monitoring with ~500ms debounce; verifies file readability to avoid partial writes.
- Enable via `DSXCONNECTOR_MONITOR=true` (see `.dev.env`).

Polling for SMB/CIFS and remote mounts
- Some CIFS/SMB mounts on Linux don’t emit inotify events for changes by remote clients. In those cases, force polling:
  - `DSXCONNECTOR_MONITOR=true`
  - `DSXCONNECTOR_MONITOR_FORCE_POLLING=true`
  - Optional: `DSXCONNECTOR_MONITOR_POLL_INTERVAL_MS=1000` (default is 1000ms)
- Helpful CIFS mount options (improve stat freshness but don’t create inotify events): `vers=3.1.1,actimeo=1,cache=strict`.

Tests for monitoring
- Unit (deterministic): `pytest -q connectors/filesystem/tests/test_filesystem_monitor.py`
  - Simulates a modify event and asserts the webhook → scan path executes (no OS watcher needed).
- Optional E2E watcher: `FS_MONITOR_E2E=true pytest -q connectors/filesystem/tests/test_filesystem_monitor_integration.py`
  - Requires `watchfiles` installed locally; starts the real watcher, drops a file, and expects a scan request.

## Running/Testing in an IDE/Debugger
All connectors can be run from the command-line or via an IDE/Debugger.  In this directory, there is both a start.py
file and `{{ cookiecutter.project_slug }}_connector.py` script either of which can be used to start the connector.

When running this way, the config.py file is read to configure the app, and any one of settings can be
overridden with environment settings.

You should see output similar to this:
```shell
2025-05-21 13:36:15,001 INFO     logging.py          : Log level set to DEBUG
INFO:     Started server process [81998]
INFO:     Waiting for application startup.
2025-05-21 13:36:15,723 INFO     dsx_connector.py    : Connection to dsx-connect at http://0.0.0.0:8586 success.
2025-05-21 13:36:15,723 INFO     filesystem_connector.py: Starting up connector filesystem-connector-0.1.0
2025-05-21 13:36:15,723 INFO     filesystem_connector.py: filesystem-connector-0.1.0 version: 0.1.0.
...
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8595 (Press CTRL+C to quit)
```

### Changing Configuration

Leave `config.py` alone — it contains sane defaults. During development, override via:

1) `.devenv` file (recommended for debugging; not included in releases)
   - Create a file named `.devenv` next to `config.py` with lines like:
     - `DSXCONNECTOR_USE_TLS=false`
     - `DSXCONNECTOR_TLS_CERTFILE=../framework/deploy/certs/dev.localhost.crt`
     - `DSXCONNECTOR_TLS_KEYFILE=../framework/deploy/certs/dev.localhost.key`
     - `DSXCONNECTOR_CONNECTOR_URL=https://filesystem-connector:8590`
     - `DSXCONNECTOR_DSX_CONNECT_URL=https://dsx-connect-api:8586`
     - `DSXCONNECTOR_VERIFY_TLS=false`
     - `DSXCONNECTOR_ASSET=~/Documents/SAMPLES`
     - `DSXCONNECTOR_FILTER=PDFs`
   - You can also point to a custom file via `DSXCONNECTOR_ENV_FILE=/path/to/file`.

2) Environment variables (works in shells/Compose/CI)
   - Any setting can be overridden as `DSXCONNECTOR_<SETTING_NAME>`.
   - Example: `DSXCONNECTOR_DSX_CONNECT_URL=https://localhost:8586`

For Compose, you can still use a `.env` file if you prefer. `.devenv` is for local debugging and is excluded from releases automatically.



## Build a Deployment Release

Connectors use Invoke to manage tasks for bundling up files, creating requirements (for pip) and
building a Docker image.  All the steps needed to prepare a new release for deployment.

### Prerequisites
Local running Docker instance: if building a Docker image (a "release")

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
* Docker images tagged with {{ cookiecutter.__release_name }}:<version> and {{ cookiecutter.__release_name }}:latest 

Other invoke options:
* bump - increments the patch version in version.py (e.g., 1.0.0 to 1.0.1). Use this for major/minor bumps before tagging if needed.
* clean - removes the distribution folder (dist/{{ cookiecutter.__release_name }}-<version>) and its associated zip file if they exist.
* prepare - prepares files for a versioned build.  Copies and moves file into dist/{{ cookiecutter.__release_name }}-<version>; generates requirements.txt.
* build - (runs bump, clean, prepare) and builds a Docker image tagged as {{ cookiecutter.__release_name }}:<version> from the prepared dist folder if it doesn’t already exist.
* push - (runs build) tags the Docker image with the repository username ({{ cookiecutter.docker_repo }}/<name>:<version>) and pushes it to Docker Hub.
* release - executes the full release cycle by running the following tasks in order: bump, clean, prepare, build, and push. Patch/build increments automatically; edit version.py manually for major/minor changes before release.
