# ADR-007: Move Repository Read Path from Connectors to Worker-Hosted Readers

- **Status:** Proposed
- **Date:** 2026-04-10
- **Decision Owners:** DSX-Connect Architecture

## Context

In the current DSX-Connect model, scan request workers dequeue scan jobs and call back to a connector to retrieve the file before submitting it to DSXA for scanning.

This works reasonably well when connectors represent relatively narrow integrations, such as a single repository or a small protected surface. However, DSX-Connect architecture is moving toward a broader model in which a single connector represents an entire tenant, site, account, or platform integration and may manage many protected scopes.

Under that model, keeping file retrieval inside the connector creates a major scalability risk:

- connectors become the data path for every file read
- full scans funnel heavy I/O through the connector tier
- connector CPU, memory, network, and connection limits become throughput bottlenecks
- scaling scan workers does not fully scale repository read throughput if the connector remains the choke point
- connector sharding becomes increasingly necessary and increasingly difficult, especially where multiple connectors cannot safely overlap on the same asset space
- broad tenant/account connectors become responsible for both control-plane logic and high-volume per-object data-plane activity

This is especially problematic for full scans, where the highest-cost and highest-volume operation is not job creation or monitoring, but object retrieval.

The current design also couples two concerns that should scale differently:

- **integration/control-plane concerns**: authentication setup, discovery, monitoring, normalization, remediation contracts, scope management
- **scan execution/data-plane concerns**: dequeuing jobs, opening object streams, sending content to DSXA, retries, throughput, backpressure

As DSX-Connect moves to tenant/account-wide connectors, that coupling becomes a growing architectural liability.

## Decision

DSX-Connect will move the repository file-read path out of connectors and into **worker-hosted Reader components**.

A generic scan request worker will remain responsible for scan execution. When processing a scan job, it will select the appropriate Reader implementation for the integration type and use that Reader to directly open the object stream from the source repository.

Examples:

- `S3Reader`
- `AzureBlobReader`
- `SharePointReader`
- `GCSReader`

Connectors will remain the integration and control-plane boundary. They will continue to own:

- connector registration and lifecycle
- configuration validation
- discovery of protectable assets
- monitoring and event intake
- normalization of object identity and repository metadata
- repository-specific remediation operations
- any platform-specific preflight or setup operations

Workers will remain generic and will continue to own:

- dequeueing scan jobs
- retry and failure handling
- DSXA submission
- result handling and persistence
- throughput and concurrency management
- scan metrics and observability

Readers will own only the worker-side repository access path needed to retrieve the object content for scanning.

## Decision Drivers

This decision is driven by the following architectural goals:

- avoid connector-tier bottlenecks as connectors broaden from per-repository to tenant/account-wide scope
- separate control-plane responsibilities from data-plane responsibilities
- allow repository read throughput to scale with worker concurrency
- remove the connector as a mandatory per-object callback in the scan hot path
- simplify the connector’s runtime role so it does not act as a file proxy for every scan
- create a cleaner long-term model for large full scans across many protected scopes

## Considered Options

### Option 1: Keep Connector Callback Read Model

In this model, the worker continues to call the connector for each file read.

#### Pros

- simplest continuation of current model
- keeps repository credentials isolated behind the connector boundary
- avoids introducing Reader plugins into workers
- keeps all repository-specific code in one place

#### Cons

- connector remains in the scan hot path
- connector becomes the main throughput bottleneck for full scans
- scaling workers does not eliminate connector-side read bottlenecks
- broad tenant/account connectors accumulate too much responsibility
- difficult to scale under the new architecture without connector sharding or other special handling
- continues to mix control-plane and data-plane concerns

#### Outcome

Rejected. This model does not fit the scaling needs of the new architecture.

---

### Option 2: Connector-Hosted Reader Pool or Reader Subprocesses

In this model, Readers are introduced, but they run alongside or underneath the connector. The worker still reads through the connector boundary, but the connector now has concurrent Reader subprocesses or an internal read pool.

#### Pros

- improves connector-side concurrency
- may reduce pressure on the connector’s main thread or process
- may preserve tighter credential containment
- can serve as an intermediate migration step

#### Cons

- connector still remains in the per-object read path
- extra network hop still exists
- connector still acts as a coordination point for every scan read
- creates risk of building a second worker/data-plane system inside the connector boundary
- partial improvement, but not true separation of control plane and data plane
- may delay adoption of the cleaner target architecture

#### Outcome

Rejected as the target architecture. May be useful as a temporary migration aid, but not the desired end state.

---

### Option 3: Worker-Hosted Readers with Generic Scan Workers

In this model, generic workers load Reader implementations and read directly from the repository.

#### Pros

- removes the connector from the per-object scan data path
- allows repository read throughput to scale with worker count
- keeps worker concurrency aligned with read concurrency
- keeps connectors focused on integration/control-plane concerns
- improves full scan scalability
- creates a cleaner long-term control-plane/data-plane split
- reduces connector resource pressure and file-proxy behavior

#### Cons

- requires a deliberate credential delivery architecture
- requires Reader code and repository SDKs to exist in the worker runtime
- requires stronger normalized job contracts for object identity and read context
- introduces versioning and compatibility considerations between connector-side logic and worker-side Readers

#### Outcome

Accepted.

## Architecture Implications

### New Component Boundary

The architecture will be split more explicitly as follows:

#### Connector Layer

Responsible for:

- integration registration
- configuration and auth validation
- discovery of protectable assets
- monitoring and event translation
- normalization of object identity
- remediation and repository-side actions
- repository metadata conventions

#### Core / Orchestration Layer

Responsible for:

- protected scope management
- job creation and queueing
- job state
- counters and authoritative processing state
- policy decisions
- assignment of integration type and read context to jobs

#### Scan Request Worker Layer

Responsible for:

- dequeueing scan jobs
- selecting the correct Reader
- invoking the Reader to open the object stream
- streaming content to DSXA
- handling retries and transient failures
- persisting results and metrics

#### Reader Layer

Responsible for:

- worker-side repository access
- object-open and stream-read operations
- repository-specific fetch behavior
- minimal translation of read-related errors into normalized worker semantics

Readers are not connectors. They are not responsible for monitoring, enumeration, or remediation. They are narrow worker-side object access components.

## Expected Benefits

The primary expected benefit is improved scalability of the read path under the new architecture.

Specifically:

- the heaviest operation, object retrieval, moves to the horizontally scalable worker tier
- connectors are no longer forced to proxy file content for every scan
- full-scan throughput can scale more naturally with worker concurrency
- connector bottlenecks become less likely as a single connector represents broader tenant/account scope
- architecture becomes cleaner by separating integration/control-plane logic from scan/data-plane execution

This decision is not expected to eliminate all integration complexity. Discovery, monitoring, scope definition, normalization, and remediation remain connector responsibilities.

It also does not eliminate the need for careful design of object identity, versioning, or credentials. Instead, it makes those explicit architectural concerns rather than hiding them behind connector callbacks.

## Risks

This decision introduces several important design risks:

### Credential Delivery

Workers will need a secure way to obtain repository access at execution time. This is now a first-class architecture concern.

### Runtime Packaging

Workers may need integration SDKs and Reader implementations for multiple platforms, increasing worker runtime complexity.

### Contract Stability

The job payload must carry enough normalized information for the Reader to identify and fetch the correct object without relying on connector-side hidden logic.

### Version Coordination

Connector-side normalization and worker-side Reader assumptions must remain compatible across releases.

## Consequences

As a result of this decision:

- `read_file` should no longer be treated as a connector service callback in the steady-state architecture
- Reader interfaces must be defined as a formal DSX-Connect abstraction
- scan jobs must include enough integration and object context for worker-side reading
- credential delivery must be designed as a dedicated architecture topic
- connectors should increasingly be treated as control-plane integrations, not scan-path data-plane services

## Follow-On Work

The following design work is required after this ADR:

1. define the Reader interface and responsibilities
2. define normalized object identity and read context in scan jobs
3. design worker-side credential delivery and credential brokerage
4. define error and retry semantics for Reader failures
5. define packaging and deployment strategy for Reader implementations in workers
6. define migration path from connector `read_file` callbacks to Reader-based fetching

## Summary

As DSX-Connect moves to tenant/account-wide connectors and multi-scope protection, connector-hosted file retrieval becomes an increasingly serious scalability bottleneck.

The architecture will therefore move to a model in which:

- connectors remain integration and control-plane components
- workers remain generic scan execution components
- Readers provide worker-side direct repository access

This places the heaviest operation, object retrieval, in the tier that is already designed to scale horizontally, and establishes a cleaner long-term separation between integration logic and scan execution.