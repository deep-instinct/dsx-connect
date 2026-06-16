# Transfer Platform Adapters

Transfer Platform Adapters are DSX-Transfer integration adapters for systems that already own file transfer workflows.

Examples:

- SFTPGo
- MOVEit
- GoAnywhere
- IBM Sterling
- Axway
- AWS DataSync-style migration services
- Google Storage Transfer Service-style migration services
- Azure Storage Mover-style migration services

## Decision

Use the term `TransferPlatformAdapter` for integrations with MFT, EFT, or migration platforms.

Do not call these integrations generic connectors.

They may consume connector capabilities internally, but their primary role is to translate an external transfer platform lifecycle into a DSX-Transfer scan and commit decision.

Architecture decision record:

- `docs/architecture-vnext/adr/adr-015-transfer-platform-adapters.md`

## Vocabulary

```text
Storage adapters:
  SourceAdapter
  SinkAdapter

Connector capabilities:
  Discoverer
  Reader
  Writer
  Remediator
  EventSource
  IdentityResolver
  CredentialProvider
  CapabilityManifest

Transfer platform integrations:
  TransferPlatformAdapter
```

Concrete adapter names:

```text
SftpGoTransferPlatformAdapter
MoveItTransferPlatformAdapter
GoAnywhereTransferPlatformAdapter
SterlingTransferPlatformAdapter
AxwayTransferPlatformAdapter
```

Current implemented adapter seam:

- `SftpGoTransferPlatformAdapter`
- `SftpGoEventContext`
- `sftpgo_context_from_payload`
- `CommitDecision`

## Role

A `TransferPlatformAdapter` receives transfer-platform context and returns a DSX-Transfer commit decision.

```text
Transfer platform event/context
  -> TransferPlatformAdapter
  -> content stream or readable reference
  -> ScanGate
  -> GuardedTransferPolicy
  -> CommitDecision
```

The transfer platform owns:

- users
- sessions
- protocols
- partner workflows
- schedules
- source/destination routing
- platform-specific transfer state

DSX-Transfer owns:

- scanner invocation
- scan result normalization
- verdict and file type policy
- commit decision
- audit/event publishing
- DSX Console visibility
- error taxonomy

## CommitDecision

The adapter should translate DSX-Transfer policy output into the platform's allow/deny mechanism.

Suggested common decision shape:

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

Example:

```json
{
  "action": "block",
  "reason": "file_type_rule:PE32FileType",
  "policy_id": "block-executables",
  "scan_guid": "scan-456",
  "file_type": "PE32FileType",
  "verdict": "benign"
}
```

## SFTPGo Example

```text
SFTPGo pre-upload event
  -> SftpGoTransferPlatformAdapter
  -> DsxaStreamScanGate
  -> GuardedTransferPolicy
  -> CommitDecision
  -> SFTPGo allow/deny
```

SFTPGo integration may start as a command or HTTP event action. The adapter turns SFTPGo-specific event fields into DSX-Transfer input and turns the DSX-Transfer decision back into SFTPGo success/failure semantics.

Current endpoint:

```text
POST /api/v1/transfer-decisions/sftpgo/pre-upload
```

Current local service command:

```bash
dsx-transfer serve \
  --host 127.0.0.1 \
  --port 8088 \
  --policy-id local-sftpgo-demo \
  --verdict /inbox/bad.exe=malicious \
  --file-type /inbox/payload.bin=PE32FileType \
  --file-type-action windows_executables=block
```

## MOVEit Example

```text
MOVEit pre-commit extension point
  -> MoveItTransferPlatformAdapter
  -> ScanGate
  -> GuardedTransferPolicy
  -> CommitDecision
  -> MOVEit allow/reject/quarantine
```

The exact mechanics depend on MOVEit's extension points, but the DSX-Transfer side should keep the same adapter/decision shape.

## Why Not Just Connector?

Connectors expose platform capabilities.

Transfer Platform Adapters translate transfer workflow lifecycle events.

Those are different responsibilities.

A storage connector might expose:

```text
Reader
Writer
Discoverer
Remediator
```

A transfer platform adapter exposes:

```text
pre-upload decision
pre-download decision
post-write fallback decision
platform event mapping
commit result mapping
```

The adapter may use connector capabilities under the hood, but it is not itself the same abstraction.

## Design Rule

```text
Use TransferPlatformAdapter when the external platform owns the transfer workflow.
Use SourceAdapter/SinkAdapter when DSX-Transfer owns the transfer workflow.
Use connector capabilities when a platform exposes reusable storage operations.
```
