# PostgreSQL and RabbitMQ Settings

DSX-Connect 2 keeps durable state in PostgreSQL and dispatches work through RabbitMQ.
This page covers how the API and workers connect to both, the settings that control them, and how the chart's embedded services are configured.

| Service | Holds | If it is lost |
| --- | --- | --- |
| PostgreSQL | Integrations, connector instances, protected scopes, jobs, job items, stage state, outbox | Configuration and scan history are gone |
| RabbitMQ | In-flight work messages, retry and dead-letter queues | Queued work is lost; durable job state in PostgreSQL remains |

!!! note "Environment variable prefix"
    Chart and image versions up to and including 2.0.33 predate the DSX-Connect 2 rename and read `DSX_CONNECT_NG_*` variables, for example `DSX_CONNECT_NG_POSTGRES__URL`.
    Later versions read the `DSX_CONNECT_V2_*` names used on this page.
    An unrecognized prefix is ignored silently, so match the prefix to the image version.

## Selecting the Backends

Both backends have in-memory fallbacks for development.
Set them explicitly for any real deployment:

```yaml
env:
  DSX_CONNECT_V2__CONTROL_PLANE_BACKEND: "postgres"
  DSX_CONNECT_V2__JOB_BUS_BACKEND: "rabbitmq"
```

| Variable | Values | Default | Notes |
| --- | --- | --- | --- |
| `DSX_CONNECT_V2__CONTROL_PLANE_BACKEND` | `postgres`, `memory`, `auto` | `auto` | `auto` tries PostgreSQL and **silently falls back to memory** if it cannot connect |
| `DSX_CONNECT_V2__JOB_BUS_BACKEND` | `rabbitmq`, `memory`, `auto` | `memory` | `memory` only works when the API and workers share a process; use `rabbitmq` with separate worker pods |

With `postgres` or `rabbitmq` set explicitly, a connection failure stops the pod at startup instead of running on in-memory state.

Check what a running deployment selected:

```bash
curl -sS "$DSX_CONNECT_URL/api/v1/architecture" | jq '{control_plane, jobs: {transport: .jobs.transport}}'
```

Worker startup logs also report `control_plane_backend` and `job_bus_backend`.

## PostgreSQL Settings

| Variable | Default | Description |
| --- | --- | --- |
| `DSX_CONNECT_V2_POSTGRES__URL` | `postgresql://dsx:dsx@127.0.0.1:5432/dsx_connect_v2` | Connection URL used by the API and all workers |
| `DSX_CONNECT_V2_POSTGRES__AUTO_APPLY_SCHEMA` | `false` | Apply the bundled SQL migrations at startup |

### Schema Migrations

The schema ships with the image as ordered SQL files under `dsx_connect_v2/migrations/`.
With `AUTO_APPLY_SCHEMA=true`, each pod applies them at startup under a PostgreSQL advisory lock, so concurrent pods do not race.
The migrations are written to be re-run safely.

Leave auto-apply on for lab and single-team deployments.
For stricter production change control, set it to `false` and apply the migrations as a separate step before upgrading the image.

### Embedded PostgreSQL

The chart can run a single PostgreSQL pod for lab use:

```yaml
postgresql:
  enabled: true
  image:
    repository: postgres
    tag: "16-alpine"
  auth:
    database: dsx_connect_2
    username: dsx
    password: dsx
  service:
    port: 5432
  # Optional PGDATA override; see below.
  dataDir: ""
  persistence:
    enabled: false
    size: 8Gi
```

The service is named `<release>-postgres`, so for a release named `dsx-connect` the URL is:

```yaml
env:
  DSX_CONNECT_V2_POSTGRES__URL: "postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2"
```

The username, password, and database in the URL must match `postgresql.auth`.

**Persistence.**
With `persistence.enabled: false`, the database is an `emptyDir` and is erased whenever the PostgreSQL pod is replaced.
Set it to `true` for anything you want to keep; the chart then creates a `ReadWriteOnce` PVC from the cluster's default StorageClass.

**`dataDir`.**
By default PostgreSQL initializes directly in the volume mount, `/var/lib/postgresql/data`.
Set `dataDir` to a subdirectory such as `/var/lib/postgresql/data/pgdata` when:

* running on OpenShift, where the random UID assigned by the `restricted-v2` SCC cannot `chmod` the mount point;
* using persistent volumes that contain a `lost+found` directory, such as GCP persistent disks, which `initdb` rejects.

Do not change `dataDir` on an existing PVC.
PostgreSQL would initialize an empty database in the new location and the existing data would no longer be used.

**Credentials.**
The chart renders `postgresql.auth` as plain environment variables on the PostgreSQL Deployment.
PostgreSQL only uses them when it initializes an empty data directory; changing them later does not change an existing database user.

### External PostgreSQL

For production, use a managed or separately operated PostgreSQL service and keep `postgresql.enabled: false`.
Put the connection URL in a Secret rather than in values:

```bash
kubectl create secret generic dsx-connect-runtime-env \
  -n dsx-connect \
  --from-literal='DSX_CONNECT_V2_POSTGRES__URL=postgresql://user:password@postgres.example:5432/dsx_connect_2'
```

```yaml
envSecretRefs:
  - dsx-connect-runtime-env
```

The database must exist and the user needs permission to create tables and indexes if `AUTO_APPLY_SCHEMA` is on.
Add libpq parameters such as `?sslmode=require` to the URL as your provider requires.

## RabbitMQ Settings

| Variable | Default | Description |
| --- | --- | --- |
| `DSX_CONNECT_V2_RABBITMQ__URL` | `amqp://guest:guest@127.0.0.1:5672/` | AMQP connection URL used by the API and all workers |
| `DSX_CONNECT_V2_RABBITMQ__RETRY_MAX_ATTEMPTS` | `5` | Retries for a retryable failure before the message moves to the DLQ |
| `DSX_CONNECT_V2_RABBITMQ__RETRY_DELAY_MS` | `5000` | Delay between retries |
| `DSX_CONNECT_V2_RABBITMQ__PUBLISHER_CONFIRMS` | `true` | Wait for broker confirmation when publishing |
| `DSX_CONNECT_V2_RABBITMQ__JOB_EXCHANGE` | `dsx.ng.jobs` | Work exchange |
| `DSX_CONNECT_V2_RABBITMQ__RETRY_EXCHANGE` | `dsx.ng.jobs.retry` | Retry exchange |
| `DSX_CONNECT_V2_RABBITMQ__DEAD_LETTER_EXCHANGE` | `dsx.ng.jobs.dlx` | Dead-letter exchange |

Leave the exchange names at their defaults unless several deployments share one RabbitMQ vhost.
Workers declare their exchanges and queues at startup.

The vhost is the URL path, URL-encoded: `/%2F` is the default vhost `/`.

For how failures move through the retry and dead-letter queues, see [Failed Scans and Dead Letter Queues](../../operations/dead-letter-queues.md).

### Embedded RabbitMQ

```yaml
rabbitmq:
  enabled: true
  image:
    repository: rabbitmq
    tag: "3.13-management-alpine"
  auth:
    username: dsx
    password: dsx
  service:
    amqpPort: 5672
    managementPort: 15672
  persistence:
    enabled: false
    size: 8Gi
```

The service is named `<release>-rabbitmq`:

```yaml
env:
  DSX_CONNECT_V2_RABBITMQ__URL: "amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F"
```

**Credentials.**
The chart passes `rabbitmq.auth` to the container as `RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS`.
The same user and password must appear in `DSX_CONNECT_V2_RABBITMQ__URL`, and they are also the Management UI login.
RabbitMQ only creates this user when its data directory is empty.
With persistence enabled, changing `rabbitmq.auth` later has no effect; change the password with `rabbitmqctl change_password` and update the URL.

The values are rendered as plain environment variables, so change the `dsx` / `dsx` defaults for any shared environment.

**Persistence.**
With `persistence.enabled: false`, queues live in an `emptyDir`.
Restarting the RabbitMQ pod drops queued messages, while job state in PostgreSQL survives.
Enable persistence if queued work must survive a broker restart.

**Management UI.**
Port 15672 serves the Management UI:

```bash
kubectl port-forward -n dsx-connect svc/dsx-connect-rabbitmq 15672:15672
```

Then open `http://127.0.0.1:15672`.

### External RabbitMQ

For production, use a managed or separately operated RabbitMQ and keep `rabbitmq.enabled: false`.
Add the URL to the same runtime Secret:

```bash
kubectl create secret generic dsx-connect-runtime-env \
  -n dsx-connect \
  --from-literal='DSX_CONNECT_V2_POSTGRES__URL=postgresql://user:password@postgres.example:5432/dsx_connect_2' \
  --from-literal='DSX_CONNECT_V2_RABBITMQ__URL=amqps://user:password@rabbitmq.example:5671/%2F'
```

Use `amqps://` and port 5671 for TLS.
The user needs configure, write, and read permissions on the vhost so workers can declare exchanges and queues.

## Lab vs Production

| Setting | Lab | Production |
| --- | --- | --- |
| `postgresql.enabled` / `rabbitmq.enabled` | `true` | `false`; use external services |
| Persistence | Optional | Managed by the external service |
| Credentials | Chart defaults | Secrets via `envSecretRefs` |
| `AUTO_APPLY_SCHEMA` | `true` | `true`, or `false` with migrations applied as a release step |
| Backends | `postgres` / `rabbitmq` explicitly | `postgres` / `rabbitmq` explicitly |
