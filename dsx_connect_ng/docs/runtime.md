# Runtime

## Install

```bash
cd dsx_connect_ng
pip install -e .
```

For worker dependencies:

```bash
cd dsx_connect_ng
pip install -e ".[workers]"
```

## API

```bash
python -m uvicorn dsx_connect_ng.app:app --host 127.0.0.1 --port 8091
```

For UI-only local preview without PostgreSQL:

```bash
DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=memory \
DSX_CONNECT_NG__JOB_BUS_BACKEND=memory \
python -m uvicorn dsx_connect_ng.app:app --host 127.0.0.1 --port 8093
```

Seed repeatable operator-console demo data in a separate terminal:

```bash
curl -X POST http://127.0.0.1:8093/api/v1/ui/demo/seed
```

This creates sample integrations, protected scopes, policies, and scan results for local preview. The endpoint is available only when `DSX_CONNECT_NG__ENVIRONMENT` is `dev`, `local`, or `test`.

## Local Runtime Manager

```bash
dsx-connect-ng-local init
dsx-connect-ng-local foreground
dsx-connect-ng-local debug --service api --service scan-worker
dsx-connect-ng-local --with-rabbit-docker foreground
dsx-connect-ng-local --with-postgres-docker --with-rabbit-docker foreground
```

The multi-process stub pipeline should use PostgreSQL because API and worker processes need shared state.

## Scanner Modes

```text
DSX_CONNECT_NG_SCANNER__MODE=stub|auto|dsxa
```

`stub` keeps synthetic scan behavior for local pipeline testing.

`dsxa` uses the real DSXA SDK path and requires scanner connection settings.

## Backends

Control-plane backend:

- `memory` for tests/local preview
- `postgres` for durable mode
- `auto` attempts PostgreSQL and falls back to memory

Job bus backend:

- `memory` for tests/local
- `rabbitmq` for durable worker transport
- `auto` attempts RabbitMQ and falls back to memory
