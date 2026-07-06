# DSX-Connect 2

DSX-Connect 2 is the next-generation DSX-Connect control plane.

It keeps the connector model from DSX-Connect 1, but changes the operational center of gravity:

* connectors register with the control plane instead of being manually configured as static integrations
* connectors advertise capabilities such as inventory discovery, scanning, monitoring, and remediation
* protected assets are assigned a protection profile that controls file-flow behavior
* PostgreSQL and RabbitMQ become first-class runtime services for durable orchestration
* workers are split by responsibility: relay, scan, policy, remediation, result sink, and DIANNA processing

The goal is a shared control plane for DSX-Connect and DSX-Transfer-style repository workflows.
Connectors normalize access to repositories such as GCS buckets, filesystem paths, cloud projects, subscriptions, or tenants.
The control plane owns asset protection, scan dispatch, policy decisions, and operator visibility.

## Current Naming

Some code paths still use the internal package name `dsx_connect_ng`.
Documentation and user-facing UI should refer to this platform as **DSX-Connect 2** or **DSX-Connect v2.x**.

## What to Read First

* [Deployment overview](deployment/index.md)
* [Deploy DSX-Connect 2 with Helm](deployment/kubernetes.md)
* [Deploy connectors](deployment/connectors.md)

## Runtime Model

For local development and Kubernetes validation, DSX-Connect 2 can run in two useful modes:

| Mode | Services | Use case |
| --- | --- | --- |
| API-only | API service with in-memory backends | UI and API smoke testing |
| Full stack | API, PostgreSQL, RabbitMQ, and workers | Connector registration, inventory, scans, and result processing |

The full stack is the expected shape for realistic testing and production planning.
