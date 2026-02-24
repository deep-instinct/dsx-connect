# Deploying DSX-Connect Core (Docker Compose)

This guide walks through running the full DSX-Connect platform (API + workers + Redis + optional log collector + optional DSXA scanner) using the Docker Compose bundle release.

Docker Compose is intended for:

* Local development
* Functional validation
* Single-host evaluation
* Demo environments

For production deployments requiring scaling, high availability, TLS automation, enrollment authentication, or resource governance, use the Helm-based Kubernetes deployment.

Bundles are published at:
[https://github.com/deep-instinct/dsx-connect/releases](https://github.com/deep-instinct/dsx-connect/releases)

Examples below assume you downloaded and extracted:

```
dsx-connect-compose-bundle-<core_version>.tar.gz
```

which expands to:

```
dsx-connect-<core_version>/
```

## Bundle Contents

Path: `dsx-connect-<core_version>/`

* `docker-compose-dsx-connect-all-services.yaml` — API, Redis, Celery workers, optional rsyslog profile, SSE dependencies.
* `docker-compose-dsxa.yaml` — optional DSXA scanner for dev/test deployments.
* `sample.core.env` — sample env file for DSX-Connect core.
* `sample.dsxa.env` — sample env file for DSXA scanner.

## Prerequisites

* Docker Desktop / Docker Engine with Compose plugin
* The Docker Compose bundle downloaded and extracted
* A shared Docker network created once:

```bash
docker network create dsx-connect-network --driver bridge
```

All compose files use this network.

---

## Deployment via Docker Compose

It is recommended to copy sample `.env` files per environment (dev/stage/etc).

Example:

```bash
cp dsx-connect-<core_version>/sample.core.env \
   dsx-connect-<core_version>/.dev.core.env
```

Use `--env-file` to select which configuration file to deploy.

Throughout this guide we refer to:

* `sample.dsxa.env`
* `sample.core.env`

### 1. Create Shared Network (once)

```bash
docker network create dsx-connect-network --driver bridge
```

### 2. Deploy DSXA Scanner (Optional)

If you already have an external DSXA scanner, skip this step.

Edit `sample.dsxa.env`:

```dotenv
DSXA_IMAGE=dsxconnect/dpa-rocky9:4.1.1.2020
APPLIANCE_URL=<di>.customers.deepinstinctweb.com
TOKEN=<DSXA token>
SCANNER_ID=<scanner id>
```

Then deploy:

```bash
docker compose \
  --env-file dsx-connect-<core_version>/sample.dsxa.env \
  -f dsx-connect-<core_version>/docker-compose-dsxa.yaml up -d
```

Verify:

```bash
docker logs <dsxa container>
```

---

### 3. Deploy DSX-Connect Stack

Edit `sample.core.env`.

Required:

```dotenv
DSXCONNECT_IMAGE=dsxconnect/dsx-connect:<version>
```

If using an external DSXA scanner:

```dotenv
DSXCONNECT_SCANNER__SCAN_BINARY_URL=http://<scanner>/scan/binary/v2
```

Deploy:

```bash
docker compose \
  --env-file dsx-connect-<core_version>/sample.core.env \
  -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml up -d
```

Verify:

* API: [http://localhost:8586](http://localhost:8586)
* `docker compose ... ps`
* `docker compose ... logs -f dsx_connect_api`

Stop:

```bash
docker compose \
  --env-file dsx-connect-<core_version>/sample.core.env \
  -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml down
```

---

## Performance and Scaling (Compose)

Docker Compose deployments are single-host and do not provide:

* Horizontal Pod Autoscaling
* Resource requests/limits
* Replica orchestration across nodes
* High-availability Redis
* Sharded connector deployments
* Cluster autoscaling

### What You Can Tune in Compose

The primary throughput control in Compose is scan-request worker concurrency.

Set in `sample.core.env`:

```dotenv
DSXCONNECT_SCAN_REQUEST_WORKER_CONCURRENCY=4
```

Then redeploy.

Increase gradually and validate using Job Comparisons.

You may also use `docker compose --scale` for experimentation, but this is not a substitute for Kubernetes-based scaling.

For full tuning methodology, see:

Operations → Performance Tuning with Job Comparisons

For production scaling mechanics, see:

Kubernetes → Scaling & Performance

---

## Authentication (Compose Scope)

Docker Compose deployments run with connector enrollment and DSX-HMAC disabled by default.

This simplifies local demos.

While authentication can be manually configured, production-grade deployments with:

* Enrollment tokens
* Secret management
* HMAC enforcement
* Rotated credentials

should use the Helm-based Kubernetes deployment.

---

## TLS Options (Compose Scope)

TLS can be configured manually via mounted certificates.

This is suitable for development environments.

For:

* Certificate automation
* Secret rotation
* Ingress integration
* Production-grade TLS management

use the Kubernetes deployment.

See: Deploying with SSL/TLS

---

## Log Collector (rsyslog)

Enable the `rsyslog` profile to collect events.

The results worker sends JSON events to `syslog:514` by default.

Override:

```dotenv
DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL
DSXCONNECT_SYSLOG__SYSLOG_SERVER_PORT
```

to point at an external collector.

---

## When to Use Kubernetes Instead

Move to the Helm-based Kubernetes deployment if you require:

* Horizontal scaling (replicas + HPA)
* Resource governance (CPU/memory requests & limits)
* Connector sharding via `DSXCONNECTOR_ASSET`
* High-availability Redis
* Production authentication enforcement
* Ingress-based TLS management
* Multi-node deployments
* Predictable scheduling and isolation
* GitOps or infrastructure-as-code workflows

Compose is ideal for development and evaluation.

Kubernetes is the supported path for operational and production environments.

---

## Common Troubleshooting

| Symptom          | Fix                                        |
| ---------------- | ------------------------------------------ |
| Port 8586 in use | Remap port or stop conflicting service     |
| Workers stuck    | Check Redis health                         |
| Large backlogs   | Increase concurrency or move to Kubernetes |
| SSE disconnects  | Use graceful shutdown                      |
| Need persistence | Mount Redis volume                         |

