# dsx-connect Core — Docker Compose

This guide walks through running the full dsx-connect platform (API + workers + Redis + optional log collector + optional DSXA scanner) using the Docker Compose bundle release. Examples below assume you downloaded and extracted `dsx-connect-compose-bundle-<core_version>.tar.gz`, which expands to `dsx-connect-<core_version>/`.

Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases)

Files in the bundle:

Path: `dsx-connect-<core_version>/`

- `docker-compose-dsx-connect-all-services.yaml` — API, Redis, Celery workers, optional rsyslog profile, SSE dependencies.
- `docker-compose-dsxa.yaml` — optional DSXA scanner for dev/test deployments (supports `AUTH_TOKEN` if enabled).
- `sample.core.env` — sample env file to pin image tags and set optional auth settings.
- `sample.dsxa.env` — sample env file for the DSXA scanner container.

## Prerequisites
- Docker Desktop / Docker Engine with the Compose plugin.
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).
- A shared Docker network created once: `docker network create dsx-connect-network` (all compose files use it).


## Deployment via Docker Compose

In this guide we will use the provided .env files to configure our deployment.  Typically one should make their own copy
of the sample env files provided and use copies of these .env files for deployments into different environments or when using 
different images, like so:.
  ```bash
  cp dsx-connect-<core_version>/sample.core.env dsx-connect-<core_version>/.prod.core.env
  ```
Then when using docker compose, use `--env-file` to point Compose at the .env of your choosing.

For the rest of this section, we will just refer to two .env files:
- `.dsxa.env`: used for configuration of DSXA scanner deployment
- `.core.env`: used for configuration of DSX-Connect core deployment

1. **Create shared network (once)**  
   ```bash
   docker network create dsx-connect-network --driver bridge
   ```
2. **Deploy DSXA scanner (optional)**
    If you already have a DSXA scanner deployed that you are planning to use, skip this step.  If you want to use a DSXA scanner deployed within the same Docker host, use this.

    Edit the .env file for DSXA as needed.  The first four configuration settings are required. 

    ```dotenv
    # Env for DSXA scanner container. Copy to xxxx.dsxa.env and set values per environment.
    
    DSXA_IMAGE=dsxconnect/dpa-rocky9:4.1.1.2020                 # used by docker-compose-dsxa.yaml
    APPLIANCE_URL=https://<di>.customers.deepinstinctweb.com   # DSXA appliance URL
    TOKEN=<DSXA token>                                         # DSXA registration token
    SCANNER_ID=<scanner id>                                    # Scanner ID
    #AUTH_TOKEN=<auth token>                                    # optional REST auth for DSXA scanner
    #FLAVOR=rest,config                                         # optional, used by docker-compose-dsxa.yaml; defaults to rest,config
    #NO_SSL=true                                                # optional, used by docker-compose-dsxa.yaml; defaults to true
    #HOST_PORT=15000                                            # optional host port override, used by docker-compose-dsxa.yaml; defaults to 5000    
    ```
   
    ```bash
    docker compose --env-file dsx-connect-<core_version>/.dsxa.env \
      -f dsx-connect-<core_version>/docker-compose-dsxa.yaml up -d
    ```
   Use `docker logs` to confirm that DSXA is running.    

3. **Deploy dsx-connect stack** 

    Use the .env file to configure settings.  There are one or two required settings.  
    `DSXCONNECT_IMAGE`: always required, specifies the where to download the DSX-Connect image
    `DSXCONNECT_SCANNER__SCAN_BINARY_URL`:

    - if you deployed the DSXA scanner via step 2. above, and 
         didn't change the port used, you can leave this commented out.  DSX-Connect will use the DSXA Scanner deployed in Step 2. at `http://dsxa_scanner:5000/scan/binary/v2`
    - if using a DSXA scanner listening on any other URL, uncomment and specify the full scan binary API path, including `http:// or https://` 
       
      ```dotenv
        # Env for DSX-Connect core. Pin image tags and supply core settings. Copy to xxxx.core.env and set values per environment (dev/stage/prod).
        
        # Core env (sample)
        DSXCONNECT_IMAGE=dsxconnect/dsx-connect:0.3.68              # used by docker-compose-dsx-connect-all-services.yaml
        ...
        
        # Optional: Override scanner URL if using an external DSXA scanner (or a custom DSXA service).
        # Default in compose points to the dsxa_scanner as deployed via docker-cmpose-dsxa.yaml.
        #DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://dsxa_scanner:5000/scan/binary/v2
        ...
        
      ```
      
   There are several other configuration options, which will be covered in Advanced Deployment below.

   ```bash
   docker compose --env-file dsx-connect-<core_version>/.core.env \
     -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml up -d
   ```
   Expected output (example):
   ```
   [+] Running 8/8
   ✔ Network dsx-connect-network                Created
   ✔ Container dsx-connect-redis-1              Started
   ✔ Container dsx-connect-rsyslog-1            Started
   ✔ Container dsx-connect-dsx_connect_api-1    Started
   ✔ Container dsx-connect-scan_request_worker-1 Started
   ✔ Container dsx-connect-verdict_action_worker-1 Started
   ✔ Container dsx-connect-results_worker-1     Started
   ✔ Container dsx-connect-notification_worker-1 Started
   ```
4. **Verify**  

   - API: http://localhost:8586  
   - `docker compose --env-file dsx-connect-<core_version>/.core.env -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml ps` to confirm healthy containers.  
   - Logs: `docker compose -f ... logs -f dsx_connect_api`

**Stop the services**  
   ```bash
   docker compose --env-file dsx-connect-<core_version>/.core.env \
     -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml down
   ```


## Common Troubleshooting

| Symptom | Fix |
| --- | --- |
| Port 8586 already in use | Edit compose file to remap API port or stop the conflicting service. |
| Workers stuck waiting for Redis | Ensure Redis health check passes; look at `docker logs dsx-connect-redis-1`. |
| SSE clients disconnecting | API has a 30s graceful shutdown window; ensure you stop the stack with `docker compose down` to let SSE flush. |
| Syslog not receiving events | Start the stack with the `rsyslog` profile, or point `DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL` at your collector. |
| Need persistent Redis | Mount a volume to `/data` in the Redis service. |
| Large backlogs | Scale `dsx_connect_scan_request_worker` (and connectors/DSXA) to increase throughput. |

# Advanced Deployment

## Authentication
- Docker Compose deployments intentionally run with connector auth disabled (no enrollment tokens, connectors unauthenticated). This keeps local demos simple.
- For production-grade deployments with enrollment + DSX-HMAC enforced, use the Helm charts (`dsx_connect/deploy/helm`) where secrets and toggles are managed securely.

## TLS Options

See [Deploying with SSL/TLS](./tls.md) for Docker Compose specifics (dev cert generation, runtime mounts, and client trust).

## Celery Workers
By default, workers in DSX-Connect fetch and process one task at a time.  The following table describes each worker, which queue it pulls tasks from and default concurrency.

| Worker | Queue | Default concurrency | Responsibilities |
| --- | --- |------------| --- |
| `dsx_connect_scan_request_worker` | `scan_request_queue` | 1 | Fetch files from connectors, submit to DSXA, enqueue verdicts. IO-bound; scale this first. |
| `dsx_connect_verdict_action_worker` | `verdict_action_queue` | 1 | Execute post-scan actions (delete/move/tag). Calls back into connectors. |
| `dsx_connect_results_worker` | `scan_result_queue` | 1 | Persist results, update stats, forward to syslog. |
| `dsx_connect_notification_worker` | `scan_result_notification_queue` | 1 | Publish events via Redis pub/sub, SSE, optional webhooks. |


To change concurrency in Docker Compose, set the env overrides in `sample.core.env`, copy it to `.core.env`, and redeploy the stack. For example:
```dotenv
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY=2
DSXCONNECT_VERDICT_ACTION_WORKER_CONCURRENCY=1
DSXCONNECT_RESULTS_WORKER_CONCURRENCY=1
DSXCONNECT_NOTIFICATION_WORKER_CONCURRENCY=1
```
The biggest throughput gains usually come from increasing `dsx_connect_scan_request_worker`, since it handles file IO + DSXA calls.

### Log Collector (rsyslog)
- Enable the `rsyslog` profile to collect events; it writes to stdout for easy `docker logs`.
- dsx_connect_results_worker sends JSON events to `syslog:514` by default. Override `DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL`/`PORT` to point at an external collector or leave unset to disable.
