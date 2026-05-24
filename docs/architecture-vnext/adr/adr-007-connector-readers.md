# ADR-007: Move Repository Read Path Behind a Reader Contract

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

DSX-Connect will move the repository file-read path behind a formal **Reader contract** executed by generic workers.

A generic scan request worker will remain responsible for scan execution. When processing a scan job, it will resolve an appropriate Reader implementation for the integration and use that Reader to obtain content for scanning.

That Reader may be:

- a **native worker-hosted Reader** that directly accesses the repository
- a **ConnectorProxyReader** that calls a connector-owned read capability, preserving the first-generation extension model

Examples of native Readers:

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

Readers will own only the repository access path needed to retrieve the object content for scanning.

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

### Option 3: Worker-Resolved Readers with Generic Scan Workers

In this model, generic workers resolve Reader implementations and obtain content through a stable Reader contract.

#### Pros

- preserves a generic worker-side read contract
- allows DI to provide native Readers for performance-critical integrations
- allows third parties to remain fully decoupled by exposing connector-side read capabilities through a ConnectorProxyReader
- permits per-integration optimization without forcing every integration into core
- keeps connectors focused on integration/control-plane concerns
- improves full scan scalability
- creates a cleaner long-term control-plane/data-plane split
- reduces connector resource pressure where native Readers are used
- keeps an extensible platform model for integrations DI does not own

#### Cons

- requires a deliberate credential delivery architecture
- native Readers require Reader code and repository SDKs to exist in the worker runtime
- requires stronger normalized job contracts for object identity and read context
- introduces versioning and compatibility considerations between connector-side normalization and Reader assumptions
- proxy Readers retain an extra hop and therefore do not eliminate all read-path overhead

#### Outcome

Accepted.

### Clarifying Addendum: Hybrid Reader Model

The Reader contract is the architectural boundary. Direct worker-hosted repository access is **not** the only valid implementation strategy.

The platform will support a hybrid model:

- **ConnectorProxyReader**
  - generic worker-side Reader implementation
  - calls a connector-owned read capability over a stable contract
  - preserves the first-generation "connectors can ship independently of core" model
- **Native Readers**
  - DI-owned optimized implementations for selected repositories
  - remove the extra connector hop when performance or control justifies tighter integration

This allows DSX-Connect to remain:

- **open by default** for third-party and separately released integrations
- **optimized selectively** where DI chooses to invest in first-order repository support

The architectural goal is therefore not "every Reader must be native in the worker runtime".
The goal is "every scan worker depends on a Reader contract rather than connector-specific read logic".

### Clarifying Addendum: Open Platform, Selective Optimization

The first-generation platform property remains important:

- connectors should still be able to ship independently of DSX-Connect core
- third parties should still be able to build supported integrations without modifying worker runtimes

The Reader contract therefore exists to decouple the **scan worker contract** from the **implementation strategy** used to obtain bytes.

The intended platform posture is:

- **open by default**
  - integrations can satisfy read semantics through a connector-owned read capability
  - workers consume that capability through a generic `ConnectorProxyReader`
- **optimized selectively**
  - DI may provide native Readers for selected repositories where the extra connector hop is too expensive or operationally limiting

This means ADR-007 is not a decision that "all read logic moves into core".
It is a decision that "all scan workers consume a stable Reader abstraction, and some Reader implementations may remain connector-backed".

### Clarifying Addendum: Readers Also Own Reuse and Preservation Paths

The Reader contract is not only the boundary for the **first read** performed by a scan worker.
It is also the correct boundary for **later content reuse** by downstream stages such as DIANNA or post-remediation validation.

This avoids pushing cross-stage preservation logic into the scan worker itself.

The intended model is:

- policy and orchestration decide whether content should be preserved for later use
- content provenance is reflected in normalized `content_source` state such as:
  - `original`
  - `cached`
  - `quarantine`
  - `none`
- later workers resolve Readers again against that updated source

Examples of Reader strategies in that model include:

- `ConnectorProxyReader`
- `NativeRepositoryReader`
- `CachedArtifactReader`
- `QuarantineReader`

DSX-Connect therefore should not encode special-case logic such as:

- "scan worker should cache bytes because DIANNA might run later"
- "DIANNA worker should know where scan worker placed a temporary file"

Instead:

- policy decides whether preservation is needed
- Readers decide how later consumers obtain bytes
- workers remain stage-focused and do not become cross-stage content managers

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
- invoking policy handoff logic after scan completion
- handling retries and transient failures
- persisting results and metrics

#### Reader Layer

Responsible for:

- repository content acquisition through a stable Reader contract
- object-open and stream-read operations
- repository-specific fetch behavior, whether direct or proxied
- minimal translation of read-related errors into normalized worker semantics
- resolving whether content should come from original source, cached artifact, or quarantine source
- hiding artifact reuse mechanics from stage workers

Readers are not connectors. They are not responsible for monitoring, enumeration, or remediation. They are narrow object access components resolved by workers.

## Expected Benefits

The primary expected benefit is improved scalability of the read path under the new architecture.

Specifically:

- the heaviest operation, object retrieval, is moved behind a worker-resolved Reader boundary
- connectors are no longer forced to proxy file content for every scan
- full-scan throughput can scale more naturally with worker concurrency where native Readers are used
- connector bottlenecks become less likely as a single connector represents broader tenant/account scope
- architecture becomes cleaner by separating integration/control-plane logic from scan/data-plane execution
- cached or quarantined content reuse can be introduced without bloating scan-worker logic

This decision is not expected to eliminate all integration complexity. Discovery, monitoring, scope definition, normalization, and remediation remain connector responsibilities.

It also does not eliminate the need for careful design of object identity, versioning, or credentials. Instead, it makes those explicit architectural concerns rather than hiding them behind connector callbacks.

## Risks

This decision introduces several important design risks:

### Credential Delivery

Workers will need a secure way to obtain repository access at execution time. This is now a first-class architecture concern.

### Runtime Packaging

Workers may need Reader implementations and repository SDKs for multiple platforms, increasing worker runtime complexity for native Readers.

### Platform Fragmentation

If proxy Readers and native Readers diverge in semantics, the platform may become inconsistent across integrations.

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
- connectors should increasingly be treated as control-plane integrations, not mandatory scan-path data-plane services
- a connector-owned read capability remains valid when exposed through a ConnectorProxyReader
- connector-side read capabilities are a first-class compatibility path, not merely a temporary migration aid
- cached and quarantine-backed reads should be treated as Reader strategies, not scan-worker special cases

## Follow-On Work

The following design work is required after this ADR:

1. define the Reader interface and responsibilities
2. define normalized object identity and read context in scan jobs
3. design worker-side credential delivery and credential brokerage
4. define error and retry semantics for Reader failures
5. define packaging and deployment strategy for Reader implementations in workers
6. define migration path from connector `read_file` callbacks to Reader-based fetching
7. define the ConnectorProxyReader request/response contract
8. define how reader selection chooses between `proxy`, `native`, `cached`, and `quarantine` strategies
9. define how integrations declare preferred and fallback reader strategies

## Summary

As DSX-Connect moves to tenant/account-wide connectors and multi-scope protection, connector-hosted file retrieval becomes an increasingly serious scalability bottleneck.

The architecture will therefore move to a model in which:

- connectors remain integration and control-plane components
- workers remain generic scan execution components
- Readers provide the worker-side content acquisition contract
- some Readers may be native and direct
- some Readers may proxy through connector-owned read capabilities

This establishes a cleaner long-term separation between integration logic and scan execution, while preserving an extensible platform model and allowing selective optimization where native Readers are worthwhile.
