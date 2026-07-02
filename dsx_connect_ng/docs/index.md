# DSX-Connect NG Docs

`dsx_connect_ng` is the standalone next-generation DSX-Connect application boundary.

It owns the new control-plane-first architecture, job orchestration model, worker contracts, result sink pipeline, local runtime, and operator UI routes.

## Start Here

- [Architecture](architecture.md)
- [Runtime](runtime.md)
- [API Boundaries](api-boundaries.md)
- [Shared Connector Control Plane](shared-control-plane.md)

## Core Principles

- Keep NG isolated from legacy `dsx_connect`.
- Make PostgreSQL and RabbitMQ first-class durable infrastructure.
- Treat connectors as integration adapters, not policy engines.
- Let connectors register runtime capabilities with the shared control plane.
- Keep API families separated:
  - control-plane APIs
  - execution APIs
  - UI APIs
- Keep worker/backend contracts out of UI routes.

## Current Major Areas

- control-plane integrations and protected scopes
- job and job-item persistence
- RabbitMQ-oriented worker topology
- worker-hosted reader abstraction
- scan, policy, remediation, result-sink, and DIANNA workers
- operator UI routes and browser console
- local runtime manager
