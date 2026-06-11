# Architecture

DSX-Transfer is a transfer engine with a mandatory scan and policy gate before destination commit.

```text
SourceAdapter -> TransferPlan -> ScanGate -> SinkAdapter -> AuditSink
                                      |
                              CheckpointStore
```

## Contracts

`SourceAdapter` owns source enumeration and item byte access.

`SinkAdapter` owns destination writes.

`TransferPlan` is the stable worklist for a migration or transfer run.

`ScanGate` reads item bytes, obtains a scanner result, evaluates policy, and returns a `ScanDecision`.

`AuditSink` records every item outcome for reporting and DSX Console-style visibility.

`CheckpointStore` records operational resume state so reruns can avoid duplicate destination writes.

## Product Boundary

Guarded Transfer should live as a sibling package/tool. It can reuse shared DSX scanner clients, policy models, audit publishing, and job-state concepts, but it should not be folded into dsx-connect as a connector.

The difference is intent:

- dsx-connect discovers, scans, and remediates content in existing repositories.
- Guarded Transfer moves content from source to sink and gates the destination commit.

## Connector Capability Model

DSX-Transfer should consume connector capabilities rather than treating connectors as monoliths.

Shared design rule:

```text
Products orchestrate workflows.
Connectors expose platform capabilities.
Shared contracts define capability boundaries.
```

For DSX-Transfer, the relevant connector capabilities are usually:

- `Discoverer` or planner support for transfer worklists
- `Reader` for source bytes
- `Writer` for destination commit
- `IdentityResolver` for stable source and sink identities
- `CredentialProvider` for platform auth
- `CapabilityManifest` for supported operations and limits

The shared model is documented in [connector-capability-model.md](../../../docs/architecture-vnext/design/connector-capability-model.md).

## Native Engine vs Platform Adapter

For the native engine, source and sink are storage systems:

```text
FilesystemSourceAdapter -> ScanGate -> GcsSinkAdapter
```

For transfer platform integrations, the adapter may be the platform itself:

```text
MoveItTransferAdapter -> ScanGate -> MoveItCommitDecision
```

In that model, MOVEit or another platform owns source/sink transport details. DSX owns the enforcement decision.

Use the `TransferPlatformAdapter` term for this family of integrations. See [transfer-platform-adapters.md](transfer-platform-adapters.md).
