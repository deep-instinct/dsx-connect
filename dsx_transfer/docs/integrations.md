# Transfer Platform Integrations

DSX-Transfer should support a native transfer engine first, then integrate with transfer platforms that customers already own.

## Enterprise MFT

Managed File Transfer platforms already handle scheduling, users, workflows, partner exchange, secure transport, compliance, and reporting. DSX should not rebuild those features.

Targets:

- Progress Software MOVEit
- Fortra
- IBM Sterling
- Axway

MOVEit is the strongest first story because many regulated customers immediately understand it.

## Engineering Exemplar: SFTPGo

SFTPGo is the preferred first integration exemplar.

It is not the commercial target, but it is open source, Docker-friendly, supports common transfer protocols and cloud storage backends, and has an event manager that can run HTTP notifications or commands for transfer events.

Use it to prove:

- pre-upload commit gating
- DSX-Transfer decision endpoint shape
- audit event usefulness
- how MFT event metadata maps to DSX transfer decisions
- how this pattern later maps to MOVEit, GoAnywhere, Sterling, or Axway

Details are in [SFTPGo Exemplar](sftpgo-exemplar.md).

## MOVEit Models

### Pre-Commit Callback

Best model if MOVEit exposes the extension point:

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

This preserves the clean destination guarantee.

### Transfer Worker Plugin

Strong model if MOVEit supports custom transfer processing:

```text
MOVEit Transfer Worker
      |
      +--> DSX Scan
      |
      +--> Destination Write
```

The scan happens inside the transfer workflow.

### Post-Write Event

Easiest model, but weakest enforcement:

```text
MOVEit -> Destination -> DSX Scan
```

This should not be the lead story because malware can exist in the destination before remediation.

## Cloud Migration Platforms

Cloud migration tools are probably the closer architectural comparison:

- AWS DataSync
- Google Storage Transfer Service
- Azure Storage Mover

Positioning:

> AWS DataSync plus malware and policy enforcement before destination commit.

## Integration / ETL Platforms

Potential later targets:

- MuleSoft
- Boomi
- Informatica

These usually focus on records, APIs, and workflows rather than file malware enforcement.
