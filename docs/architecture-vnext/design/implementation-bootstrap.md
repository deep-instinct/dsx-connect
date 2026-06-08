# VNext Implementation Bootstrap

This document defines how implementation should begin without coupling the new architecture to the current `dsx_connect` runtime.

## Decision

Implementation starts in a standalone application package:

- `dsx_connect_ng/`

This is not a preview mode inside `dsx_connect`.

## Why

The current `dsx_connect` application contains useful preview experiments, but those previews are not the long-term architecture boundary.

The next-generation app needs:

- its own package and dependency graph
- its own FastAPI app
- its own PostgreSQL schema ownership
- its own RabbitMQ topology
- its own worker runtime
- its own tests and CI

## Separation Rules

1. `dsx_connect_ng` must not import `dsx_connect.*`.
2. Legacy preview routers are reference material only.
3. Legacy DLQ patterns should not be copied into vnext.
4. RabbitMQ dead-lettering should be implemented with broker-native exchanges and queue policies.
5. PostgreSQL remains the source of truth for control-plane and job state.
6. API surfaces must be split into:
   - control-plane APIs for configuration and intent
   - execution APIs for scan-path work and backend coordination
   - UI APIs for frontend/operator experiences

## API Surface Split

Do not create a single mixed API tree where connector contracts and frontend contracts live together without distinction.

Required separation:

- `/api/v1/control-plane/...`
  - integration registration
  - connector status and capabilities
  - scope/job/policy metadata
  - configuration and orchestration intent

- `/api/v1/execution/...`
  - scan submission
  - fetch/read/finalize/remediate execution contracts
  - worker/service-to-service operations
  - broker-oriented machine workflows

- `/api/v1/ui/...`
  - dashboard reads
  - operator actions
  - presentation-oriented summaries
  - frontend-specific composition

Reason:

- execution contracts need stronger stability than presentation contracts
- control-plane contracts express what the system should do
- execution contracts express how backend work gets done
- UI contracts can evolve for usability without destabilizing the backend integration surface
- this avoids repeating one of the common legacy failure modes where internal/backend contracts and presentation contracts collapse into one API layer

## Start Order

1. control-plane schema and migrations
2. integration + protected-scope API
3. scope matcher and no-overlap validation
4. canonical domain job envelope
5. RabbitMQ publishers/consumers
6. worker-hosted Readers
7. pilot connector in shadow mode

## Current Scaffold

The initial application scaffold lives under:

- [dsx_connect_ng/README.md](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/README.md:1)
- [dsx_connect_ng/dsx_connect_ng/app.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/app.py:1)
- [dsx_connect_ng/dsx_connect_ng/config.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/config.py:1)
- [dsx_connect_ng/dsx_connect_ng/api/routes/control_plane.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/api/routes/control_plane.py:1)
- [dsx_connect_ng/dsx_connect_ng/api/routes/execution.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/api/routes/execution.py:1)
- [dsx_connect_ng/dsx_connect_ng/api/routes/ui.py](/Users/logangilbert/PycharmProjects/dsx-connect/dsx_connect_ng/dsx_connect_ng/api/routes/ui.py:1)

For the first thin operator UI built on top of this split, see:

- [Rudimentary Operator UI Plan](/Users/logangilbert/PycharmProjects/dsx-connect/docs/architecture-vnext/design/rudimentary-operator-ui-plan.md:1)
