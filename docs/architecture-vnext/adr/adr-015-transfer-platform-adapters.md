# ADR-015: Transfer Platform Adapters for External Transfer Workflows

- **Status:** Proposed
- **Date:** 2026-06-10
- **Decision Owners:** DSX Architecture
- **Related:** ADR-008 (Capability-Based Integration Model), DSX-Transfer Transfer Platform Adapters

## Context

DSX-Transfer supports native guarded transfer workflows where DSX owns the transfer lifecycle:

```text
SourceAdapter -> ScanGate -> SinkAdapter
```

That model fits migrations and direct movement between storage systems such as filesystem, GCS, S3, Azure Blob, or connector-backed repositories.

There is a separate integration category where DSX does not own the transfer lifecycle. Managed file transfer, enterprise file transfer, and cloud migration platforms already provide:

- scheduling
- user and partner management
- workflow routing
- secure transport
- reporting
- platform-native transfer state

Examples include SFTPGo, MOVEit, GoAnywhere, IBM Sterling, Axway, AWS DataSync-style services, Google Storage Transfer Service-style services, and Azure Storage Mover-style services.

For these platforms, DSX-Transfer should not become a replacement transfer engine. DSX should act as the malware-aware policy and commit-decision layer.

## Decision

DSX will use the term **Transfer Platform Adapter** for integrations where an external transfer platform owns the file transfer workflow and DSX-Transfer provides the scan and commit decision.

The primary interface name is:

```text
TransferPlatformAdapter
```

Concrete adapters should use platform-specific names:

```text
SftpGoTransferPlatformAdapter
MoveItTransferPlatformAdapter
GoAnywhereTransferPlatformAdapter
SterlingTransferPlatformAdapter
AxwayTransferPlatformAdapter
```

These adapters are not generic DSX-Connect connectors, although they may use connector capabilities internally.

## Responsibility Boundary

A `TransferPlatformAdapter` translates platform lifecycle events into DSX-Transfer decisions.

```text
Transfer platform event/context
  -> TransferPlatformAdapter
  -> content stream or readable reference
  -> ScanGate
  -> GuardedTransferPolicy
  -> CommitDecision
  -> platform allow/block/quarantine action
```

The transfer platform owns:

- users and sessions
- protocols
- partner workflows
- schedules
- source and destination routing
- platform-specific transfer state
- native reporting and operator workflows

DSX-Transfer owns:

- scanner invocation
- scan result normalization
- verdict policy
- DSXA-determined file type policy
- allow, block, exclude, quarantine, and manual-review decisions
- audit and event publishing
- DSX Console visibility
- DSX error taxonomy

## Vocabulary

Use these terms consistently:

```text
Native transfer storage contracts:
  SourceAdapter
  SinkAdapter

Shared connector capabilities:
  CapabilityManifest
  CredentialProvider
  IdentityResolver
  Discoverer
  Reader
  Writer
  Remediator
  EventSource

External transfer workflow integrations:
  TransferPlatformAdapter
```

## Commit Decision Shape

Transfer platform adapters should translate DSX policy output into a common commit decision before mapping that decision to platform-specific allow, deny, quarantine, or fallback behavior.

Suggested common shape:

```text
CommitDecision
  action: allow | block | exclude | quarantine | manual_review | error
  reason: string
  policy_id: string
  scan_guid: string
  file_type: string
  verdict: string
  audit_event_id: string
  details: object
```

The platform adapter may add platform-specific fields, but the core DSX decision should remain portable across MFT, EFT, and migration integrations.

## Design Rules

Use `TransferPlatformAdapter` when the external platform owns the transfer workflow.

Use `SourceAdapter` and `SinkAdapter` when DSX-Transfer owns the transfer workflow.

Use connector capabilities when a platform exposes reusable storage operations such as discovery, read, write, remediation, identity resolution, or credential brokerage.

## Rationale

Calling these integrations generic connectors blurs two different roles:

- connectors expose reusable platform capabilities
- transfer platform adapters translate a third-party transfer lifecycle into DSX commit decisions

The distinction matters because DSX-Transfer should be able to integrate with existing enterprise transfer platforms without rebuilding the enterprise transfer product surface those platforms already provide.

This also supports least privilege. A platform adapter can require only the permissions needed for a specific lifecycle decision, while connector-backed source and sink adapters can request separate read, write, discovery, or remediation permissions when DSX owns the transfer.

## Consequences

DSX-Transfer gains a clear integration model for SFTPGo, MOVEit, GoAnywhere, Sterling, Axway, and cloud migration services.

DSX-Connect and DSX-Transfer can still share connector capability contracts without forcing every product integration to be called a connector.

Product documentation can position DSX-Transfer as:

> a malware-aware commit gate for native transfer workflows and external transfer platforms.

Implementation work should avoid putting MFT-specific concepts into the native `SourceAdapter` and `SinkAdapter` contracts. Platform lifecycle concerns belong in transfer platform adapters.
