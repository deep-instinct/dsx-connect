# Getting Started: Overview

## Purpose
Get up and running quickly by deploying everything on your own machine. 

We'll get you set up to scan files you already have right on your own device,
so there’s no extra setup or data wrangling. You’ll deploy DSXA (scanner) + DSX-Connect core, 
and a Connector. Each page ends with a **Next** link to keep you moving.

## Prerequisites
- Docker Desktop or Docker Engine with the Compose plugin.
- The DSX-Connect release bundle (`compose-bundle-<version>.tar.gz`) extracted locally (see Section below). It contains the compose files referenced below.
- Network access to your Deep Instinct Management Console appliance.

## Getting and using the Compose bundle

Download the latest release bundle from the
<a href="https://github.com/deep-instinct/dsx-connect/releases" target="_blank" rel="noopener noreferrer">
DSX-Connect releases page
</a>.
There will be several releases—grab the asset named `compose-bundle-<version>.tar.gz` (typically the newest one).
Extract the bundle to a local directory (example below uses `0.3.57`; swap in your version):

```bash
tar -xzf compose-bundle-0.3.57.tar.gz
```

After extracting, you should see:

```bash
compose-bundle-0.3.57/
  docker-compose-dsxa.yaml
  docker-compose-dsx-connect-all-services.yaml
  sample.core.env
  sample.dsxa.env
  aws-s3-connector-0.5.36/
  ...
  filesystem-connector-0.5.24/
    sample.filesystem.env
    docker-compose-filesystem-connector.yaml
```
In the topmost directory, you'll find the compose files you'll use to deploy DSX-Connect and DSXA scanner.  Note the version number (in this case 0.3.57)- 
this is the version of the DSX-Connect release that the ...dsx-connect-all-services.yaml has been tested against.

- ```docker-compose-dsxa.yaml```: This is a helper compose file to quickly deploy a single DSXA scanner 
instance in Docker - only supports the API /scan/binary/v2 (and thus limited in the file size scannable) and no support for high-availability or scaling. Useful for testing, development and simple single instance deployments of DSXA. 
Please refer to the DSX for Applications documentation for more information on how to deploy and use this scanner.

- ```docker-compose-dsx-connect-all-services.yaml``` deployment for the DSX-Connect core stack. 

- ```sample.core.env``` is a sample environment file that you can use as a starting point for dsx-connect core configuration.  
- ```sample.dsxa.env``` is a sample environment file for the DSXA scanner container.
Example below:
```dotenv
# Env for DSX-Connect core. Pin image tags and supply optional DSXA/auth settings. Copy to .core.env and set values per environment (dev/stage/prod).

# Core env (sample)
DSXCONNECT_IMAGE=dsxconnect/dsx-connect:0.3.57
DSXA_IMAGE=dsxconnect/dpa-rocky9:4.1.1.2020
```
Note that in this example image tags are set to a specific version (e.g. "dsx-connect:0.3.57"), but these can be changed to use earlier or later versions of those images.
We will address how to use .env files and the compose files together in the next sections.

### Connector deployment compose files
In the subdirectories, you'll find the compose files for individual Connectors, and like the core compose file, they contain a `docker-compose-<connector>.yaml` and a sample environment file.

### DSX-Connect Docker images

The Docker images for all DSX-Connect core elements and Connectors are available on Docker Hub:
- [dsxconnect/dsx-connect](https://hub.docker.com/r/dsxconnect)

All of the deployment mechanisms used throughout this guide will download images from this repository. The docker compose files reference the images by tag, so you can change the tag to use a different version, or even a different repository, but most
of the time you can stick with the defaults.

## Recommended local resources
- CPU: 4+ cores
- RAM: 8 GB+
- Disk: a few GB free for images and logs
- Docker Desktop (macOS/Windows): allocate at least 4 CPUs and 8 GB RAM to Docker if available.

## Install Docker
- Docker Desktop: [macOS](https://docs.docker.com/desktop/install/mac-install/), [Windows](https://docs.docker.com/desktop/install/windows-install/)
- Docker Engine (Linux): [install guide](https://docs.docker.com/engine/install/)
- macOS lightweight alternative: [Colima](https://github.com/abiosoft/colima) (uses Lima; often lighter than Docker Desktop).  Homebrew install: ```brew install colima```
- Windows alternatives: [Rancher Desktop](https://rancherdesktop.io/) or [Podman Desktop](https://podman-desktop.io/) with Docker-compat mode via WSL2.

### Install Docker Compose (if not bundled)
- Docker Desktop includes Compose v2 out of the box.
- Linux (Docker Engine): install the Compose plugin:
  ```bash
  sudo curl -L "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
  sudo chmod +x /usr/local/bin/docker-compose
  docker compose version
  ```
  Or use your package manager (`docker-compose-plugin`).
- Rancher Desktop / Podman Desktop: enable Docker-compatible CLI so `docker compose` works.
   

## Prepare the shared network
Create the shared bridge network once; every compose file uses it:
```bash
docker network create dsx-connect-network
```
Confirm the network exists:
```bash
docker network ls
```
output:
```bash
NETWORK ID     NAME                  DRIVER    SCOPE
e7cbf5ac2957   bridge                bridge    local
b15b2bab8be1   dsx-connect-network   bridge    local
```

## What you’ll deploy

- DSXA scanner (via `docker-compose-dsxa.yaml`)
- DSX-Connect core (API, workers, Redis, UI) via `docker-compose-dsx-connect-all-services.yaml`
- A sample connector (filesystem) on the same bridge network

Continue to the core deployment to start the stack.

[Next: Deploying the DSX-Connect Core](getting-started-core.md)
