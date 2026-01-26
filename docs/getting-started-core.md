# Deploying the DSX-Connect Core

In the following, we will deploy DSXA (the scanner) and DSX-Connect core on Docker on your local machine using Docker Compose and the compose-bundle you downloaded earlier.

## How we use Docker Compose here
- **Compose files as templates**: `docker-compose-dsxa.yaml` and `docker-compose-dsx-connect-all-services.yaml` declare the services, network, and volumes. Think of them as deployment templates you can reuse across environments.
- **Environment files for config**: Instead of editing the compose files directly, use the sample env files included in the bundle. For core we’ll start from `.sample.core.env` and copy it to `.core.env`, then adjust values (URLs, tokens, ports) as needed. This keeps the compose files static and makes overrides easy.

## 1) Launch DSXA (scanner)

From the extracted bundle directory, reuse the same env file you’ll use for core:
```bash
cp .sample.core.env .core.env   # if you haven’t already
# edit .core.env to set APPLIANCE_URL, TOKEN, SCANNER_ID
# optionally set DSXA_IMAGE, FLAVOR, NO_SSL, HOST_PORT, AUTH_TOKEN
```

Example `.core.env` (core settings first, DSXA settings below):
```dotenv
# Core settings (dsx-connect)
DSXCONNECT_IMAGE=dsxconnect/dsx-connect:0.3.58
#DSXCONNECT_ENROLLMENT_TOKEN=your-token   # optional, only if you enable auth

# DSXA scanner settings (used by docker-compose-dsxa.yaml)
APPLIANCE_URL=https://acme.customers.deepinstinctweb.com
TOKEN=abcd1234-your-dsxa-token
SCANNER_ID=dsxa-scanner-01
DSXA_IMAGE=dsxconnect/dpa-rocky9:4.1.1.2020
FLAVOR=rest,config
NO_SSL=true
HOST_PORT=15000
AUTH_TOKEN=    # optional (leave blank if DSXA auth is disabled)
```
Note: please see the DSX for Applications Deployment Guide for more details on how to obtain the `APPLIANCE_URL` and `TOKEN`, and 
a complete list of available DSXA scanner settings.

Then deploy DSXA with that env file:
```bash
docker compose --env-file .core.env -f docker-compose-dsxa.yaml up -d
```

Next, you can look at the scanner logs to confirm that it started and is initialized.  You can start by running:
```bash 
docker ps
```
Which will show you all of the running containers on docker.  You should see an entry for the scanner:
```cmd
CONTAINER ID   IMAGE                                            COMMAND                  CREATED        STATUS                    PORTS                                           NAMES
4cd87c9aa51e   dsxconnect/dpa-rocky9:4.1.1.2020                 "/bin/bash -c 'sourc…"   6 seconds ago   Up 5 seconds               0.0.0.0:15000->5000/tcp, [::]:15000->5000/tcp   dsxa_scanner-1
```

Note the name of the container, which is `dsxa_scanner-1` in this example.  To look at the scanner logs:
```bash
docker logs dsxa_scanner-1
```
You should see something like this:
```cmd
Starting Deep Instinct DPA 4.1.1.2020p
Running on OS:  Rocky Linux 9.6 (Blue Onyx)
sysctl: permission denied on key "kernel.core_pattern"
Starting DI REST Server
```
and eventually:
```bash
2025-12-12 14:57:52.383164 I p:23 t:53 ../Client/Classifier/src/Classifier/MultiBrainLib.cpp:393: Classifier initialized. Result: true
```
That's an indicator that the scanner is up and running.



Notes:

- DSXA binds to `dsx-connect-network` on the docker local port '5000' and exposes port `5000` on the host via `HOST_PORT` (default 15000). Set `HOST_PORT` in your env to override without editing YAML.
- In docker compose, the 'up' command asks docker to start all services defined in the compose file.  -d means 'detached mode', which means the services will run in the background.
- 

## 2) Launch DSX-Connect core

Reuse the `.core.env` from the previous step (or copy the sample now if you skipped DSXA):
```bash
cp .sample.core.env .core.env   # skip if already done
# edit .core.env to set DSXCONNECT_IMAGE (and optional auth/DSXA settings)
```

Bring up API, workers, Redis, UI using that env file:
```bash
docker compose --env-file .core.env -f docker-compose-dsx-connect-all-services.yaml up -d
```

## 3) Verify health
```bash
docker compose -f docker-compose-dsx-connect-all-services.yaml ps
```
You should see the API (`dsx-connect-api`), workers, Redis, and support services. The UI becomes available at `http://localhost:8586/`.

Open a browser and navigate to `http://localhost:8586/`. You should see the DSX-Connect UI.

![img.png](img.png)

Notice that the UI is connected to the scanner running on port 15000 as indicated by the "Connected:..." message.  If you see this message you
are on the right track!  Congratulations!

From here you can look at the core config, the RestAPI, change visual aspects, but we aren't yet to the point of scanning files, which is what we will do next.

[Next: Deploying Your First Connector](getting-started-connector.md)

## Troubleshooting
Run ```bash docker ps```

```
bd2b23ddd997   dsxconnect/dsx-connect:0.3.57      "python dsx_connect/…"   38 hours ago     Up 38 hours (unhealthy)   0.0.0.0:8586->8586/tcp, :::8586->8586/tcp       dsx_connect_api-1
```
```bash
docker logs dsx_connect_api-1
```
