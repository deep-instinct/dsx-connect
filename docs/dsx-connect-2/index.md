# DSX-Connect 2

DSX-Connect 2 is the next-generation DSX-Connect control plane for securing file flow across enterprise repositories.
It keeps the core idea that made DSX-Connect useful: repositories are integrated through connectors instead of hardcoded into the platform.
The major change is scope.

In DSX-Connect 1, a connector often represented a single repository target such as one GCS bucket or one filesystem path.
In DSX-Connect 2, a connector can represent a broader platform boundary: a tenant, cloud project, subscription, account, storage estate, or repository service.
The connector becomes the normalized integration point for that platform, and DSX-Connect owns the operational decisions about which assets are protected, which scans are running, which protection profile applies, and what happened to each object.

The result is a cleaner separation between repository integration and secure data-flow control.
Developers can focus on application and repository behavior.
Security and operations teams can define how files are discovered, scanned, monitored, remediated, and reported without asking application teams to build that logic repeatedly.

## High-Level Concepts

### Connectors Represent Platform Integrations

A connector is the integration boundary between DSX-Connect and a repository platform.
Depending on the platform, one connector may represent:

* a GCS project
* an Azure subscription
* an AWS account
* a SharePoint or OneDrive tenant
* a filesystem estate
* a single repository when that is the right operational boundary

The connector registers with DSX-Connect and advertises what it can do.
Those capabilities may include discovery, enumeration, monitoring, reading objects, and remediation.
This lets DSX-Connect reason about integrations consistently without embedding platform-specific behavior in the operator experience.

### Assets Are Protected Under the Connector

Assets are the protectable resources exposed by a connector.
For object storage, an asset might be a bucket.
For collaboration platforms, an asset might be a site, library, drive, or tenant-scoped repository.
For filesystems, it might be a mounted path or share.

Protection can be assigned broadly or narrowly:

* enable protection for all discovered assets under a connector
* enable protection for a filtered subset, such as bucket names beginning with a prefix
* enable or disable protection on individual assets
* use API-driven bulk operations for large environments
* use the UI for operator-driven exceptions and investigation

This is important for scale.
An organization may have hundreds or thousands of buckets, sites, shares, or storage locations.
DSX-Connect 2 is designed so protecting those assets does not require deploying hundreds or thousands of connector instances.

### Protection Profiles Control File Flow

Protection profiles define what DSX-Connect should do after scanning and classification.
The current model is intentionally simple:

* detect only
* quarantine
* delete, where supported and allowed
* file-type rules that treat selected content types as non-compliant
* quarantine path settings

The protection profile is assigned when an asset is protected.
Changing a connector default affects newly assigned protections, while existing protected assets keep the profile already assigned to them.
This makes broad defaults practical while still allowing exceptions.

### The Control Plane Owns State, Policy, and Visibility

DSX-Connect 2 moves scan orchestration, policy decisions, and operational visibility into a durable control plane.
PostgreSQL stores control-plane and job state.
RabbitMQ carries work between services.
Workers are split by responsibility:

* relay
* scan
* policy
* remediation
* result sink
* DIANNA processing

This makes the platform more resilient than a connector-only flow.
If a connector, worker, or API process restarts, accepted work can be recovered from durable state rather than being lost in process memory.

## What DSX-Connect 2 Adds Over DSX-Connect 1

### Self-Registering Connectors

Connectors register with DSX-Connect instead of requiring every integration to be manually configured as a static endpoint.
At startup, a connector tells DSX-Connect:

* who it is
* which platform it represents
* which tenant/project/subscription/account key it maps to
* its endpoint
* its capabilities
* its health and lease window

The operator console can then show live, stale, and offline connectors based on heartbeats.
This gives a more natural Kubernetes and container deployment model: deploy the connector, and the control plane discovers it.

### Capability-Based Integrations

DSX-Connect 2 treats integrations as sets of capabilities.
A connector may support discovery but not monitoring.
Another may support monitoring and remediation.
A future connector may represent an entire tenant and expose many asset types beneath it.

This lets the platform grow without requiring every connector to look identical.
It also lets DSX-Connect and DSX-Transfer-style workflows share the same control-plane pattern over time.

### Bulk Protection Without Losing Granularity

Most environments want a default posture.
For example, all buckets in a project may normally use the same protection profile.
DSX-Connect 2 supports that model by letting connector-level defaults drive asset protection.

At the same time, operations teams still need exceptions.
An individual asset may need a different protection profile, a temporary detect-only posture, or protection disabled.
The model supports both:

* one bulk API or UI action for many assets
* granular overrides where the operations team needs precision

This is the difference between a platform model and a connector-per-repository model.

### Discovery and Monitoring Are First-Class

Discovery is how DSX-Connect learns what can be protected.
Monitoring is how DSX-Connect reacts to new or changed content.

For example, a GCS connector can discover buckets and subscribe to Pub/Sub notifications for object events.
When a new object arrives, the connector normalizes the event and submits scan work into the DSX-Connect 2 execution API.
The scan workers then process the object through the same durable job pipeline used for manual and bulk scans.

That gives a consistent operational view whether a scan was started by:

* an operator
* a bulk protection workflow
* a scheduled or full scan
* a repository event

### Separation of Duties

DSX-Connect 2 creates a practical separation between development, platform operations, and security operations.

Application and repository teams can focus on:

* building applications
* owning data locations
* managing normal platform configuration
* providing credentials or deployment context where required

Security and operations teams can own:

* which repositories are protected
* which protection profile applies
* how malicious, non-compliant, or unscanned files are handled
* scan visibility and operational response
* remediation posture
* evidence, reporting, and result forwarding

This reduces the need for every application team to implement secure file-flow behavior themselves.
DSX-Connect becomes the shared security control for repository-backed file movement.

### Easier Deployment and Release Management

DSX-Connect 2 is designed for standard container and Kubernetes workflows.
The platform can be deployed as a Helm release with API, PostgreSQL, RabbitMQ, and workers.
Connectors are deployed as their own Helm releases and register into the control plane.

Images and charts are published separately:

* application images are pushed as Docker/OCI images
* Helm charts are pushed as OCI chart artifacts
* connector images and connector charts are versioned together

This supports local k3s testing, CI/CD release builds, and production-style deployments without relying on locally built images as the source of truth.

## Why This Matters

DSX-Connect 2 changes DSX-Connect from a set of individually configured connector deployments into a repository security control plane.

That matters because enterprise storage is broad, dynamic, and operationally uneven.
Some assets need broad default protection.
Some need exceptions.
Some platforms support event monitoring.
Some only support polling or scheduled scans.
Some teams can remediate automatically.
Others need detect-only visibility first.

The control-plane model handles those differences explicitly:

* connectors normalize platform access
* assets define what can be protected
* protection profiles define secure file-flow behavior
* jobs track work durably
* workers execute scan, policy, remediation, and result delivery
* the operator console gives a single view across connectors and assets

## Current Naming

Some code paths still use the internal package name `dsx_connect_ng`.
Documentation and user-facing UI should refer to this platform as **DSX-Connect 2** or **DSX-Connect v2.x**.

## What to Read First

* [Deployment overview](deployment/index.md)
* [Deploy DSX-Connect 2 with Helm](deployment/kubernetes.md)
* [Deploy connectors](deployment/connectors.md)
* [Packaging releases](packaging-releases.md)

## Runtime Model

For local development and Kubernetes validation, DSX-Connect 2 can run in two useful modes:

| Mode | Services | Use case |
| --- | --- | --- |
| API-only | API service with in-memory backends | UI and API smoke testing |
| Full stack | API, PostgreSQL, RabbitMQ, and workers | Connector registration, inventory, scans, and result processing |

The full stack is the expected shape for realistic testing and production planning.
