# Bootstrap Plan

This package is the implementation root for DSX-Connect NG.

## Start Here

1. implement PostgreSQL-backed control-plane schema and migrations
2. implement integration and protected-scope APIs
3. implement scope matcher with no-overlap validation
4. implement canonical domain-job envelope
5. add RabbitMQ publisher/consumer topology
6. add worker-hosted Reader abstraction
7. pilot one integration in shadow mode

## RabbitMQ Position

RabbitMQ is the message transport and redelivery mechanism for DSX-Connect NG workers.

Implications:

- do not port legacy in-process DLQ handling from `dsx_connect`
- use RabbitMQ dead-letter exchanges and queue policies for poison-message routing
- use PostgreSQL for authoritative job state and audit
- workers should update durable job state before acking broker delivery

Control-plane backend policy:

- `memory` is allowed for local development and tests
- `postgres` is the only durable control-plane backend
- `redis` is not a primary control-plane backend choice

## First Tickets

1. `control_plane`: add SQL migration set and repository interface
2. `api`: add `integrations` and `protected_scopes` CRUD endpoints
3. `scope_engine`: add write-time overlap validator and runtime matcher
4. `jobs`: add canonical job envelope models
5. `workers`: add RabbitMQ topology declaration module
