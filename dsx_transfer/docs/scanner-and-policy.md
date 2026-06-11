# Scanner and Policy

The current implementation uses `StaticVerdictScanGate` for deterministic local tests and demos. It does not use DSXA yet.

The intended real scanner path is a DSXA stream scan gate.

```text
SourceAdapter.open_item()
  -> DsxaStreamScanGate
  -> GuardedTransferPolicy
  -> ScanDecision
```

## Stream Scan First

Streaming should be the default DSXA integration for Guarded Transfer.

Reasons:

- It fits the transfer engine, which already reads each item.
- It avoids the more complex DSXA by-path deployment model.
- It lets Guarded Transfer own item-level concurrency.
- It avoids relying on DSXA embedded file-walking or scan concurrency.
- It keeps the product story focused on inline commit gating.

## By-Path Scan As Explicit Mode

By-path scanning should be an explicit special mode, not the default.

Use it for:

- very large files, especially files larger than the normal stream limit
- deployments where DSXA is colocated with mounted storage
- cases where a scanner-supported by-path mode is operationally simpler

Do not lead with by-path for the native filesystem migration path.

## Policy Evaluation

The scanner should not directly decide only from verdict. The scan result should flow through a Guarded Transfer policy evaluator:

```text
DSXA scan result
  -> normalized verdict + detected file type
  -> GuardedTransferPolicy.evaluate(scan_result, item)
  -> ScanDecision
```

The current package has this evaluator in code as `GuardedTransferPolicy`. `StaticVerdictScanGate` and `DsxaStreamScanGate` both feed a `ScanObservation` into that evaluator, so verdict rules and detected-file-type rules are shared across static tests and real DSXA scanning.

`DsxaStreamScanGate` targets the DSXA SDK's async `scan_binary_stream(...)` shape. It accepts any client object with that method, which keeps tests on a fake client while allowing production wiring to use `AsyncDSXAClient`.

Policy inputs should include:

- DSXA verdict
- DSXA detected file type
- item size
- source identity
- destination identity
- transfer metadata

## Detected File Type Rules

File type policy should use DSXA's detected file type, not the extension. This is post-scan enforcement based on real content classification.

Example policy behaviors:

- block a detected executable even if it has a harmless extension
- exclude a detected file type from transfer without treating it as malware
- route a detected archive or encrypted archive to manual review

Example policy sketch:

```yaml
policy_id: guarded-migration-default
verdict_rules:
  malicious: block
  suspicious: block
  unknown: block
file_type_rules:
  PE32FileType: block
  OOXMLFileType: exclude
  ZIPFileType: manual_review
```

Useful actions:

- `allow`: transfer the file
- `block`: do not transfer and record as blocked
- `exclude`: do not transfer and record as excluded by policy
- `manual_review`: do not automatically transfer
- `quarantine`: later, write to a quarantine target instead of the clean destination

The model should distinguish extension filters from DSXA file type policy:

```text
extension-based filtering = pre-scan convenience filter
DSXA file type policy = post-scan enforcement
```

For local testing before DSXA integration, the CLI can simulate detected file types:

```bash
dsx-transfer migrate \
  --source ~/Documents/SAMPLES/0Simple \
  --destination ~/Documents/dsx-transfer/dests \
  --transfer-id local-demo \
  --policy-id filetype-demo \
  --file-type payload.bin=PE32FileType \
  --file-type-action windows_executables=block
```

Policy rules should prefer DSXA file type names directly. Supertype groups are optional convenience aliases that expand to concrete DSXA file types. Current groups include:

- `windows_executables`: `PEFileType`, `PE32FileType`, `PE64FileType`
- `linux_executables`: `ELF32FileType`, `ELF64FileType`
- `macos_executables`: `MachoFATFileType`, `Macho32FileType`, `Macho64FileType`
- `executables`: all of the above

## Concurrency and Batch Scanning

Guarded Transfer should first get concurrency by scanning multiple independent transfer items at once with a bounded worker pool.

That preserves the per-file commit gate:

```text
item stream -> DSXA stream scan -> policy decision -> destination commit
```

A DSXA batch scan API may be useful later if it can return per-file verdicts cleanly and does not weaken destination commit semantics. It should not be the first concurrency mechanism.

Preferred order:

1. bounded item-level concurrency in `TransferEngine`
2. DSXA stream scan per item
3. optional future batch scan mode if DSXA supports the right per-file result contract

Batch scanning can amortize request overhead, but it complicates audit, checkpointing, retry, and per-file allow/block decisions. For DSX-Transfer, commit gating is more important than maximizing scanner batching early.
