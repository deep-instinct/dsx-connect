# DSX-Transfer

DSX-Transfer is the proposed product name for guarded file migration and exchange. Guarded Transfer is the initial capability: malware-aware, policy-enforced file movement with a scan gate before destination commit.

It should reuse shared DSX scanner, policy, event, and SDK code where practical, but it should not be treated as a dsx-connect connector feature by default.

The package-local docs live under `dsx_transfer/docs/`. Treat those as the implementation-adjacent design notes as this moves from concept to code.

The core workflow is:

```text
Source storage -> DSX inline scan decision -> Destination storage
```

Benign files are copied or moved to the destination. Malicious files, unknown files above a configured threshold, or files that violate policy are blocked and recorded for DSX Console visibility and audit.

## Use Cases

- Move files from a file share to GCS while scanning inline.
- Move files from one file share to another file share while preventing malicious files from landing in the target.
- Add a malware and policy gate to an application-managed upload, ingest, or migration workflow.
- Integrate DSX scanning into a third-party managed file transfer or cloud migration platform.

## Product Shapes

### SDK and Developer Tooling

This shape is for teams embedding guarded transfer behavior into their own applications.

Possible interfaces:

```python
guarded_transfer.copy(
    source="file:///mnt/source/report.pdf",
    destination="gcs://clean-bucket/archive/report.pdf",
    policy="block-malicious",
)
```

Lower-level SDK APIs should support source streams, sink writers, scan decisions, and audit emission so application teams can control their own transfer lifecycle.

A VS Code extension or similar developer plugin could scaffold migration code, run local test transfers, and show DSX verdict or audit records while developers integrate.

### Standalone Migration Tool

This shape is a CLI or lightweight UI where an operator chooses a source and sink and DSX handles enumeration, streaming, scanning, enforcement, checkpointing, and reporting.

Example:

```bash
dsx-transfer migrate \
  --source /mnt/fileshare \
  --destination gcs://customer-clean-bucket/prefix \
  --policy block-malicious \
  --report migration-report.jsonl \
  --resume-state .dsx-transfer-state
```

Likely first pairs:

- mounted filesystem or file share -> GCS
- mounted filesystem or file share -> another filesystem or file share
- mounted filesystem or file share -> S3 or Azure Blob

This is the cleanest first product and demo because DSX owns the transfer path and can enforce pre-commit decisions.

### Third-Party Transfer Integration

This shape plugs DSX into an existing file exchange, managed transfer, or cloud migration platform.

Possible integration points:

- pre-commit webhook or callback before the destination write is finalized
- sidecar scanner in a transfer worker
- source or destination proxy that all transfer bytes pass through
- custom connector or plugin for a migration platform
- post-write event scanner with quarantine or delete actions

Post-write integrations are easier to attach to native cloud migration services, but they are weaker from an enforcement perspective because malicious content can exist in the destination before remediation runs.

## Enforcement Models

### Pre-Commit Scanning

The file is scanned before it is committed to the final destination.

Advantages:

- Malicious files do not land in the clean destination.
- Audit and compliance posture are stronger.
- The destination can be treated as policy-clean.

Tradeoffs:

- Large files require careful streaming or staging design.
- Destination writes are delayed until a verdict is available.
- Transfer retries and partial writes must be handled deliberately.

This is the primary differentiated model for DSX-Transfer.

### Post-Write Scanning

The file lands in the destination and DSX scans it afterward.

Advantages:

- Easier to attach to native migration tools and cloud object events.
- Less control over the transfer engine is required.

Tradeoffs:

- Malicious files can exist in the destination for a window of time.
- DSX needs quarantine, delete, move, or tag permissions on the destination.
- The security guarantee is weaker for regulated migrations.

Post-write scanning may be useful for third-party integrations, but it should not define the main product.

## Proposed Architecture

```text
SourceAdapter -> TransferPlanner -> ScanGate -> SinkAdapter -> Audit/Event Sink
```

### Source Adapters

- local filesystem
- mounted SMB, NFS, or enterprise file share paths
- S3
- GCS
- Azure Blob
- SharePoint or OneDrive later

### Sink Adapters

- local filesystem
- mounted SMB, NFS, or enterprise file share paths
- S3
- GCS
- Azure Blob

### Scan Gate

The scan gate is the enforcement point. It should produce a decision before destination commit:

- `allow`
- `block`
- `quarantine`
- `manual_review`
- `error`

The implementation may stream bytes directly to the scanner, stage content in temporary storage, or use a scanner-supported by-path mode depending on file size, source type, destination type, and scanner capability.

### Audit and Reporting

Each transfer attempt should emit enough information for DSX Console and local reports:

- source URI
- destination URI
- object identity
- file size
- hash when available
- scan verdict
- policy decision
- enforcement action
- policy version or policy ID
- transfer status
- timestamps
- retry count
- error details when applicable

## MVP

Build the standalone migration tool first.

Initial scope:

- source: local or mounted filesystem
- sink: GCS
- scan mode: inline pre-commit
- policy: allow benign, block malicious or configured unknown threshold
- audit: DSX Console event plus local JSONL report
- resumability: checkpoint by source path plus size, mtime, and optionally hash
- concurrency: bounded worker pool
- failures: retry transient scan/copy errors and record terminal failures

Follow-on scope:

- filesystem -> filesystem
- filesystem -> S3
- filesystem -> Azure Blob
- cloud object storage as source
- UI wrapper
- SDK extraction from the CLI engine
- third-party migration platform integrations

## Phase 2: Transfer Platform Integrations

MOVEit integration is one of the strongest Phase 2 stories because MOVEit already solves scheduling, user management, workflows, partner exchanges, secure transport, and reporting.

DSX should not rebuild those capabilities. In that model, DSX becomes the security enforcement layer inside or beside an existing transfer platform.

### Model 1: Pre-Commit Callback

This is the best integration model if the transfer platform exposes the right extension point.

```text
Sender
   |
MOVEit
   |
DSX Scan Decision
   |
Allow ---> Destination
Block ---> Reject / Quarantine
```

MOVEit calls DSX before the file is finalized. This preserves the same clean destination guarantee as the native Guarded Transfer engine.

The main technical question is whether MOVEit exposes a sufficiently flexible pre-commit extension point.

### Model 2: Transfer Worker Plugin

This can be even stronger architecturally if MOVEit supports custom transfer processing inside the transfer workflow.

```text
MOVEit Transfer Worker
      |
      +--> DSX Scan
      |
      +--> Destination Write
```

The scan happens inside the transfer worker before the destination write is committed.

### Model 3: Post-Write Event

This is usually the easiest integration model.

```text
MOVEit
   |
Destination
   |
DSX Scan
```

This should not be the lead story. It works, but malware can exist in the destination for some period of time, which is the risk Guarded Transfer is intended to eliminate.

### Product Positioning

DSX-Transfer should have two related surfaces:

- DSX-Transfer: native transfer engine.
- DSX-Transfer Integrations: security enforcement for existing transfer and migration platforms.

The native engine owns source enumeration, scanning, destination writes, audit, and checkpointing.

The integration surface uses the same policy engine and scan gate, but a different transport engine.

Likely integration targets:

- MOVEit
- GoAnywhere
- AWS DataSync
- Azure Storage Mover
- Google Storage Transfer Service

For a platform integration, the adapter may be the transfer platform itself rather than a source or sink storage system:

```text
MoveItTransferAdapter
        |
     ScanGate
        |
MoveItCommitDecision
```

In this model, source and sink details are owned by MOVEit. DSX evaluates content and returns an enforcement decision.

### Roadmap Placement

A practical roadmap is:

1. Native Guarded Transfer CLI/tool: filesystem -> GCS.
2. Filesystem -> S3 and filesystem -> Azure Blob.
3. SDK.
4. MOVEit integration.
5. GoAnywhere integration.
6. AWS DataSync integration.

The expected customer path is that a native migration project proves the value of inline scanning. The next question will often be whether DSX can enforce the same policy in the transfer platform the customer already owns.

## Market Categories

There are three adjacent categories DSX-Transfer could plug into.

### Enterprise Managed File Transfer

These platforms already handle scheduled file movement, secure transport, user management, partner exchange, workflow automation, compliance, and audit.

DSX should not try to replace those systems. The product story is that DSX adds a malware and policy enforcement layer to an existing MFT estate.

Important platforms:

- Progress Software MOVEit
- Fortra
- IBM Sterling
- Axway

MOVEit is probably the clearest first-name customer story because it is recognizable in government, healthcare, financial services, and other regulated environments. A customer can quickly understand the phrase: "DSX-Transfer integrates with MOVEit."

Fortra has a large enterprise footprint, strong workflow automation, and a similar regulated-industry customer profile.

IBM Sterling is common in very large enterprises, banks, insurance, B2B exchange, and supply chain environments.

Axway is a large enterprise integration platform with strong international presence.

### Cloud Migration Platforms

This category may be the stronger architectural comparison because Guarded Transfer is fundamentally a migration engine with a mandatory security gate.

Important platforms:

- Google Storage Transfer Service
- AWS DataSync
- Azure Storage Mover

These platforms are good at moving data between file systems, cloud object stores, and on-prem environments, but malware and policy enforcement before destination commit is not their main value proposition.

The differentiating model is:

```text
NAS -> DSX-Transfer -> S3
```

instead of:

```text
NAS -> DataSync -> S3
```

For Google, the common migration stories include filesystem -> GCS, S3 -> GCS, and Azure -> GCS.

For AWS, the relevant surfaces include NFS, SMB, EFS, S3, and on-prem to cloud movement. AWS DataSync is probably the closest workflow comparison.

For Microsoft, the story is migration-oriented rather than security-oriented.

### Integration and ETL Platforms

These platforms move data around organizations, but they usually focus more on records, APIs, application integration, and business workflows than file malware enforcement.

Important platforms:

- MuleSoft
- Boomi
- Informatica

They may become integration targets later, but they are not the clearest first comparison for malware-aware transfer.

## Positioning Opportunity

DSX-Transfer is not primarily competing with MOVEit.

It is closer to:

```text
Malware-Aware Transfer
```

or:

```text
Guarded Migration
```

The common enterprise pattern today is:

```text
Source
  ->
Migration Tool
  ->
Destination
  ->
Security Scan Later
```

Guarded Transfer changes the commit path:

```text
Source
  ->
Scan Gate
  ->
Destination
```

That is materially different because Deep Instinct becomes a mandatory commit gate rather than a scanner that reacts after content lands.

The companies to study most closely for architecture and buyer expectations are probably AWS, Google, and Microsoft. The product is closer to a migration engine than a traditional MFT platform, with DSX enforcing malware and policy decisions before destination commit.

One concise positioning line:

> AWS DataSync plus malware and policy enforcement before destination commit.

## Initial Package Slice

The initial implementation lives in `dsx_transfer/` as a sibling Python package.

Current contracts:

- `SourceAdapter`
- `SinkAdapter`
- `TransferPlan`
- `ScanGate`

Current runnable path:

- filesystem source adapter
- filesystem sink adapter
- transfer engine
- static verdict scan gate for deterministic tests and demos
- Typer CLI entry point: `dsx-transfer migrate`

Example local run:

```bash
PYTHONPATH=dsx_transfer ./.venv/bin/python -m dsx_transfer.cli migrate \
  --source /tmp/source \
  --destination /tmp/destination \
  --transfer-id local-demo \
  --policy-id block-malicious \
  --verdict bad.exe=malicious \
  --audit-jsonl /tmp/dsx-transfer-audit.jsonl \
  --checkpoint /tmp/dsx-transfer-checkpoint.json
```

Run the initial tests with:

```bash
PYTHONPATH=dsx_transfer ./.venv/bin/python -m pytest dsx_transfer/tests
```

## Shared Foundation, Different Product Intent

DSX-Transfer is orthogonal to dsx-connect, but it should share foundation code where the boundaries are clean.

Reuse from dsx-connect:

- connector and storage adapter patterns
- source and sink identity models
- scanner client contracts
- verdict, action, and policy models
- connector credential patterns
- audit and event publishing
- job state, progress, and checkpoint concepts

Guarded Transfer has different product intent:

- dsx-connect discovers, scans, and remediates content in existing repositories.
- Guarded Transfer moves content from a source to a sink and gates the destination commit.
- Guarded Transfer has first-class source and sink adapters.
- Transfer resumability, idempotent destination writes, metadata preservation, and throughput/backpressure are core concerns.

Guarded Transfer should introduce its own first-class contracts:

- `SourceAdapter`
- `SinkAdapter`
- `TransferPlan`
- `ScanGate`

The initial implementation should live as a sibling package or tool and depend on shared DSX libraries rather than being folded into dsx-connect as another connector.
