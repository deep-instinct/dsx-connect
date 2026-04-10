**# Design Note: Integration Registration Model for Connectors and Readers

- **Status:** Proposed
- **Date:** 2026-04-10

## Purpose

This note defines the registration concept for the new DSX-Connect architecture in which:

- **connectors** remain the control-plane integration point
- **Readers** become the data-plane read capability used by generic workers
- **workers** remain generic and do not hardcode knowledge of S3, Azure Blob, SharePoint, or other repositories

The purpose of registration is to preserve an important DSX-Connect property:

> a new integration should be introduced by deploying the integration package, not by modifying core worker logic

## Problem

In the Reader-based architecture, workers must be able to retrieve repository objects directly for scanning.

However, DSX-Connect should avoid a design in which workers contain hardcoded logic such as:

- `if integration_type == "s3": use S3Reader`
- `if integration_type == "sharepoint": use SharePointReader`

That would create tight coupling between worker runtime and specific integrations, and would weaken the current extensibility model where a new connector can be introduced without changing the core platform.

## Decision

DSX-Connect will use a **registration-based capability model**.

Each integration package will register its capabilities with the platform at deployment or startup time.

At minimum, an integration may register:

- a **Connector capability** for control-plane operations
- a **Reader capability** for worker-side repository reads

Workers will not know about individual integration implementations directly. Instead, they will resolve the correct Reader through a registry using a stable integration or reader identifier carried in the scan job.

## Core Principle

Workers depend on a **Reader contract**, not on repository-specific implementations.

This means:

- workers know how to ask for a Reader
- workers do not know how S3, Azure Blob, SharePoint, GCS, or other platforms work internally
- the integration package supplies the implementation behind the contract

## High-Level Model

### Connector

The Connector remains responsible for control-plane integration concerns such as:

- integration registration
- configuration validation
- discovery of protectable assets
- monitoring and event intake
- normalization of object identity
- remediation actions
- repository metadata conventions

### Reader

The Reader is the worker-side data-plane capability responsible for:

- opening an object stream for scanning
- translating normalized read context into repository-specific fetch operations
- returning read failures in normalized form

The Reader is intentionally narrow. It is not responsible for monitoring, discovery, or remediation.

### Worker

The scan request worker remains generic and is responsible for:

- dequeuing jobs
- resolving the correct Reader through the registry
- invoking the Reader with normalized read context
- streaming content to DSXA
- retries, failure handling, and result persistence

## Registration Concept

When an integration is deployed, it should register both sides of its functionality:

- **Connector registration**: "I provide control-plane support for this integration type"
- **Reader registration**: "I provide worker-side read support for this reader type"

Conceptually:

- connector registers: `integration_type = aws.s3`
- reader registers: `reader_type = aws.s3`

A scan job then carries enough metadata for the worker to resolve the correct Reader.

## Example Registration Flow

### Integration Deployment Time

An AWS S3 integration package is deployed.

It registers:

- Connector capability for `aws.s3`
- Reader capability for `aws.s3`

### Job Creation Time

When Core creates a scan job for an S3 object, it includes:

- integration type
- reader type
- normalized object identity
- read context
- credential or access-context reference

### Worker Execution Time

The worker:

1. dequeues the job
2. reads `reader_type = aws.s3`
3. asks the Reader registry for the implementation of `aws.s3`
4. invokes that Reader with the provided read context
5. receives a stream and sends it to DSXA

The worker never contains repository-specific branching logic.

## Registry Model

The term **registry** in this architecture refers to a capability lookup mechanism, not necessarily a network-distributed service registry.

The preferred meaning is:

> a stable mechanism by which integrations register implementations, and workers resolve them by type

### Preferred Form: Logical / In-Process Registry

The preferred model is a local runtime registry within the worker environment.

For example:

- Reader implementations are loaded into the worker runtime
- each Reader registers itself at startup
- the worker resolves the Reader by identifier

Conceptually:

`ReaderRegistry.register("aws.s3", S3Reader)`

And later:

`reader = ReaderRegistry.get("aws.s3")`

This preserves local execution and avoids reintroducing a network hop.

### Non-Goal: Remote Reader Service Registry

The registry should **not** be implemented as a remote per-read lookup service that causes workers to call out across the network for object access.

That would risk recreating the very connector callback pattern the Reader design is meant to eliminate.

## Deployment Model

The cleanest deployment model is to treat Connector and Reader as two capabilities belonging to the same integration package.

Conceptually:

```text
aws-s3-integration/
  connector/
  reader/**

````markdown
# Design Note: Integration Registration Model for Connectors and Readers

- **Status:** Proposed
- **Date:** 2026-04-10

## Purpose

This note defines the registration concept for the new DSX-Connect architecture in which:

- **connectors** remain the control-plane integration point
- **Readers** become the data-plane read capability used by generic workers
- **workers** remain generic and do not hardcode knowledge of S3, Azure Blob, SharePoint, or other repositories

The purpose of registration is to preserve an important DSX-Connect property:

> a new integration should be introduced by deploying the integration package, not by modifying core worker logic

## Problem

In the Reader-based architecture, workers must be able to retrieve repository objects directly for scanning.

However, DSX-Connect should avoid a design in which workers contain hardcoded logic such as:

- `if integration_type == "s3": use S3Reader`
- `if integration_type == "sharepoint": use SharePointReader`

That would create tight coupling between worker runtime and specific integrations, and would weaken the current extensibility model where a new connector can be introduced without changing the core platform.

## Decision

DSX-Connect will use a **registration-based capability model**.

Each integration package will register its capabilities with the platform at deployment or startup time.

At minimum, an integration may register:

- a **Connector capability** for control-plane operations
- a **Reader capability** for worker-side repository reads

Workers will not know about individual integration implementations directly. Instead, they will resolve the correct Reader through a registry using a stable integration or reader identifier carried in the scan job.

## Core Principle

Workers depend on a **Reader contract**, not on repository-specific implementations.

This means:

- workers know how to ask for a Reader
- workers do not know how S3, Azure Blob, SharePoint, GCS, or other platforms work internally
- the integration package supplies the implementation behind the contract

## High-Level Model

### Connector

The Connector remains responsible for control-plane integration concerns such as:

- integration registration
- configuration validation
- discovery of protectable assets
- monitoring and event intake
- normalization of object identity
- remediation actions
- repository metadata conventions

### Reader

The Reader is the worker-side data-plane capability responsible for:

- opening an object stream for scanning
- translating normalized read context into repository-specific fetch operations
- returning read failures in normalized form

The Reader is intentionally narrow. It is not responsible for monitoring, discovery, or remediation.

### Worker

The scan request worker remains generic and is responsible for:

- dequeuing jobs
- resolving the correct Reader through the registry
- invoking the Reader with normalized read context
- streaming content to DSXA
- retries, failure handling, and result persistence

## Registration Concept

When an integration is deployed, it should register both sides of its functionality:

- **Connector registration**: "I provide control-plane support for this integration type"
- **Reader registration**: "I provide worker-side read support for this reader type"

Conceptually:

- connector registers: `integration_type = aws.s3`
- reader registers: `reader_type = aws.s3`

A scan job then carries enough metadata for the worker to resolve the correct Reader.

## Example Registration Flow

### Integration Deployment Time

An AWS S3 integration package is deployed.

It registers:

- Connector capability for `aws.s3`
- Reader capability for `aws.s3`

### Job Creation Time

When Core creates a scan job for an S3 object, it includes:

- integration type
- reader type
- normalized object identity
- read context
- credential or access-context reference

### Worker Execution Time

The worker:

1. dequeues the job
2. reads `reader_type = aws.s3`
3. asks the Reader registry for the implementation of `aws.s3`
4. invokes that Reader with the provided read context
5. receives a stream and sends it to DSXA

The worker never contains repository-specific branching logic.

## Registry Model

The term **registry** in this architecture refers to a capability lookup mechanism, not necessarily a network-distributed service registry.

The preferred meaning is:

> a stable mechanism by which integrations register implementations, and workers resolve them by type

### Preferred Form: Logical / In-Process Registry

The preferred model is a local runtime registry within the worker environment.

For example:

- Reader implementations are loaded into the worker runtime
- each Reader registers itself at startup
- the worker resolves the Reader by identifier

Conceptually:

`ReaderRegistry.register("aws.s3", S3Reader)`

And later:

`reader = ReaderRegistry.get("aws.s3")`

This preserves local execution and avoids reintroducing a network hop.

### Non-Goal: Remote Reader Service Registry

The registry should **not** be implemented as a remote per-read lookup service that causes workers to call out across the network for object access.

That would risk recreating the very connector callback pattern the Reader design is meant to eliminate.

## Deployment Model

The cleanest deployment model is to treat Connector and Reader as two capabilities belonging to the same integration package.

Conceptually:

```text
aws-s3-integration/
  connector/
  reader/
````

They may run in different runtime locations, but they should be versioned and developed as part of the same integration contract.

This ensures that:

* object identity assumptions remain consistent
* read context format remains consistent
* connector-side normalization and worker-side reading evolve together

## Integration Contract

Connector and Reader together define a single integration contract.

That contract must include at least:

* integration type identifier
* reader type identifier
* normalized object identity schema
* normalized read context schema
* error mapping expectations
* credential access expectations

This is important because the Reader can no longer rely on hidden connector-side logic to interpret repository-specific details at read time.

## Why This Model Is Needed

This registration model exists to solve two competing needs at the same time:

### Need 1: Remove Connector Bottlenecks

As connectors become tenant-, site-, or account-wide, the connector cannot remain the per-object data path for every scan.

The read path must move to the worker tier so that high-volume object retrieval scales with worker concurrency.

### Need 2: Preserve Extensibility

DSX-Connect should not regress into a model where every new integration requires manual worker code changes.

Workers should remain generic and capability-driven.

The registry model allows DSX-Connect to move the heavy read path out of connectors without hardcoding integration-specific logic into workers.

## Benefits

### Preserves Generic Workers

Workers remain repository-agnostic and execute against a stable Reader contract.

### Preserves Integration Extensibility

A new integration is introduced by deploying a new integration package that registers its capabilities.

### Supports Horizontal Scale

The data-plane read path now lives in the worker tier, which is the tier already intended to scale for throughput.

### Creates a Clean Capability Model

The platform can reason in terms of capabilities rather than hardcoded component types.

For example:

* this integration supports `read`
* this integration supports `monitor`
* this integration supports `remediate`

### Aligns with Future Architecture

This model fits the broader DSX-Connect direction in which:

* connectors represent broader platform integrations
* protected scopes are owned by core
* workers execute normalized jobs
* heavy per-object operations occur in scalable execution tiers

## Tradeoffs and Constraints

### Reader Must Exist in Worker Runtime

A Reader-based integration still requires the Reader implementation to be available where workers execute.

This means the integration is not purely connector-only anymore.

### Version Coordination Matters

Connector and Reader must be treated as parts of one contract and should not drift independently.

### Registration Alone Does Not Solve Credentials

The registry tells the worker **which Reader** to use, but not yet **how that Reader obtains repository access safely**.

Credential delivery remains a separate architecture concern.

### Packaging Strategy Must Be Defined

DSX-Connect will need a clear packaging and deployment model for Reader implementations, whether through bundled integration packages, plugins, or another controlled extension mechanism.

## Non-Goals

This design note does not define:

* credential brokerage or credential delivery
* the precise Reader interface
* plugin packaging or hot-loading mechanics
* remote execution of Readers as a network service
* remediation capability registration beyond the conceptual model

Those topics should be addressed in follow-on notes.

## Recommended Architectural Statement

A concise way to describe this model is:

> Integrations register capabilities with the platform. Connectors provide control-plane capabilities. Readers provide worker-side read capabilities. Workers remain generic and resolve Readers through a registry rather than hardcoding repository-specific logic.

## Summary

The registration concept allows DSX-Connect to move repository reads out of the connector hot path without losing the pluggable integration model.

Under this design:

* connectors remain the control-plane integration boundary
* Readers become the worker-side data-plane read capability
* workers remain generic
* a registry maps integration identifiers to Reader implementations
* Connector and Reader are treated as two capabilities of one integration contract

This preserves extensibility while enabling the read path to scale in the worker tier rather than bottlenecking in broad tenant/account connectors.
