# What This Is

DSX-Transfer is a malware-aware transfer and guarded migration product.

It provides enough transfer capability to move files safely, but its primary value is the security enforcement layer:

```text
Source
  -> Read
  -> ScanGate
  -> Policy Decision
  -> Destination Commit
```

The central promise is clean destination enforcement. Files that are malicious, policy-blocked, excluded, or require manual review should not be committed to the clean destination.

## What This Is

DSX-Transfer is:

- a native transfer engine for security-led file movement
- a guarded migration tool
- a scan-and-policy gate before destination commit
- an audit trail for allowed, blocked, excluded, skipped, and failed files
- a resumable transfer workflow with checkpoints
- a reusable SDK/engine for application-embedded guarded movement
- an integration layer for existing Managed File Transfer platforms

The native engine should be good enough for enterprise migration and movement workflows where the security gate is the point.

It should support:

- source planning and enumeration
- source reads
- destination writes
- inline DSXA scanning
- verdict and detected-file-type policy
- audit events
- checkpoints and resume
- bounded concurrency
- retries for transient failures
- clear reporting

## What This Is Not

DSX-Transfer is not a full Enterprise Managed File Transfer replacement.

It should not try to rebuild:

- partner management
- user portals
- inbox/outbox user experiences
- managed SFTP, FTPS, or HTTPS server endpoints
- enterprise scheduling suites
- complex approval workflows
- EDI or B2B orchestration
- nonrepudiation features
- full compliance reporting suites
- multi-tenant MFT administration
- every workflow feature in MOVEit, GoAnywhere, Sterling, or Axway

Those platforms already solve operational transfer management. DSX-Transfer should integrate with them rather than replace them.

## Product Boundary

The right framing is:

```text
Good-enough enterprise transfer
+
malware-aware commit gate
+
integration layer for existing MFT platforms
```

DSX-Transfer should own the path where security enforcement is inseparable from transfer:

```text
source planning
  -> read
  -> scan
  -> policy
  -> destination commit
  -> audit/checkpoint
```

MFT platforms should own broader operational workflows:

```text
users
  -> partners
  -> schedules
  -> managed protocols
  -> enterprise workflows
  -> business reporting
```

## Native Engine

The native engine should prove the value of inline scanning and support customers who need a direct migration path.

Examples:

- filesystem -> GCS
- filesystem -> S3
- filesystem -> Azure Blob
- filesystem -> filesystem
- cloud storage -> cloud storage

Native engine features should be included when they support:

- clean destination guarantees
- auditability
- resumability
- least-privilege source and sink credentials
- policy enforcement
- operationally practical migrations

## Platform Integrations

DSX-Transfer should also work as a plugin or enforcement layer for existing transfer platforms.

Examples:

- MOVEit
- GoAnywhere
- IBM Sterling
- Axway
- AWS DataSync-style migration platforms
- Google Storage Transfer Service-style platforms
- Azure Storage Mover-style platforms

The preferred integration model is pre-commit:

```text
MFT / migration platform
  -> DSX ScanGate
  -> Allow / Block / Quarantine / Manual Review
```

Post-write scanning can exist as a fallback integration, but it should not be the lead story because it allows malicious content to land before DSX acts.

## Connector Relationship

DSX-Transfer should consume connector capabilities through transfer adapters.

For example:

```text
TransferEngine
  -> SinkAdapter
      -> ConnectorWriterSinkAdapter
          -> Connector Writer capability
```

This preserves the DSX-Transfer engine boundary while allowing connector reuse.

The design rule is:

```text
Products orchestrate workflows.
Connectors expose platform capabilities.
Shared contracts define capability boundaries.
```

## Scope Test

Use this test for future feature decisions:

If the feature is required for secure transfer, clean destination enforcement, audit, checkpointing, retry, concurrency, or least-privilege platform access, it probably belongs in DSX-Transfer.

If the feature is primarily partner workflow management, user portal behavior, managed protocol hosting, enterprise scheduling, or B2B transfer administration, it probably belongs in an MFT platform integration.

## Summary

DSX-Transfer is not an MFT replacement.

It is a malware-aware commit gate with enough transfer capability to stand alone when needed and enough integration flexibility to secure existing enterprise transfer platforms.
