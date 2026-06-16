# DSX-Transfer Docs

DSX-Transfer is the product/package name. Guarded Transfer is the initial capability: malware-aware, policy-enforced file movement with a scan gate before destination commit.

It reuses DSX scanner, policy, audit, and job-state ideas where practical, but its product intent is different from dsx-connect.

Core workflow:

```text
Source storage -> ScanGate -> Destination storage
```

The destination write is gated by the scan and policy decision. Benign files are transferred. Malicious files, policy-blocked file types, or files that cross configured thresholds are blocked or excluded and recorded.

## Current Implementation

The initial package is in `dsx_transfer/`.

Implemented contracts:

- `SourceAdapter`
- `SinkAdapter`
- `ScanGate`
- `AuditSink`
- `CheckpointStore`
- `TransferPlan`
- `TransferItem`
- `ScanDecision`
- `TransferReport`

Implemented runnable path:

- filesystem source adapter
- filesystem sink adapter
- GCS sink adapter
- shared object storage capability contracts
- GCS writer wrapper over the GCS connector client
- transfer engine
- Guarded Transfer policy evaluator
- static verdict scan gate
- DSXA stream scan gate seam
- static detected-file-type inputs for local policy testing
- JSONL audit sink
- JSON checkpoint store
- Typer CLI

Run tests:

```bash
PYTHONPATH=dsx_transfer ./.venv/bin/python -m pytest dsx_transfer/tests
```

Install editable:

```bash
./.venv/bin/python -m pip install -e ./dsxa_sdk_py -e ./dsx_transfer
```

When running directly from source without installing editable packages, include both package roots:

```bash
PYTHONPATH=dsx_transfer:dsxa_sdk_py ./.venv/bin/python -m dsx_transfer.cli --help
```

Manual local run:

```bash
mkdir -p ~/Documents/dsx-transfer/dests

dsx-transfer migrate \
  --source ~/Documents/SAMPLES/0Simple \
  --destination ~/Documents/dsx-transfer/dests \
  --transfer-id local-demo \
  --policy-id block-malicious \
  --verdict bad.exe=malicious \
  --file-type payload.bin=PE32FileType \
  --file-type-action windows_executables=block \
  --audit-jsonl ~/Documents/dsx-transfer/dests/audit.jsonl \
  --checkpoint ~/Documents/dsx-transfer/dests/checkpoint.json
```

Shared config run:

```bash
dsx-transfer migrate --config dsx-transfer.yaml
```

Config support commands:

```bash
dsx-transfer config init --preset filesystem-to-gcs --output dsx-transfer.yaml
dsx-transfer config validate --config dsx-transfer.yaml
dsx-transfer config schema
```

`dsx-transfer.yaml` is the portable handoff object between the CLI, local UI, VS Code extension, and future automation. Relative filesystem paths in the config resolve from the config file directory. Secrets should stay out of the file; use Google ADC, `GOOGLE_APPLICATION_CREDENTIALS`, workload identity, or environment-provided DSXA auth values.

For cloud storage providers, DSX-Transfer should use the same provider capability wrappers as connectors. The current GCS sink path is:

```text
GcsSinkAdapter -> GCSWriter -> GCSClient -> google-cloud-storage
```

`GcsSinkAdapter` calls `GCSWriter.validate()`, which delegates to `GCSClient.ensure_ready()`, during construction so missing SDK, credentials, or bucket access fail before source scanning. The source path should mirror this with the existing `GCSDiscoverer` and `GCSReader` wrappers:

```text
GcsSourceAdapter -> GCSDiscoverer + GCSReader -> GCSClient -> google-cloud-storage
```

Example:

```yaml
version: 1

transfer:
  id: fs-to-gcs-demo
  policy_id: block-malicious

source:
  kind: filesystem
  path: /mnt/source-share

destination:
  kind: gcs
  uri: gs://customer-clean-bucket/archive

scanner:
  mode: dsxa
  dsxa:
    base_url: https://scanner.example.com

policy:
  verdict_actions:
    benign: allow
    malicious: block
    suspicious: block
    unknown: block
  file_type_actions:
    windows_executables: block

runtime:
  audit_jsonl: .dsx-transfer/audit/fs-to-gcs-demo.jsonl
  checkpoint: .dsx-transfer/checkpoints/fs-to-gcs-demo.json
```

Filesystem to GCS run:

```bash
dsx-transfer migrate \
  --source /mnt/source-share \
  --destination gs://customer-clean-bucket/archive \
  --destination-kind gcs \
  --transfer-id fs-to-gcs-demo \
  --policy-id block-malicious \
  --scanner-mode dsxa \
  --dsxa-base-url https://scanner.example.com \
  --dsxa-auth-token "$DSXA_AUTH_TOKEN" \
  --audit-jsonl /tmp/dsx-transfer-fs-to-gcs-audit.jsonl \
  --checkpoint /tmp/dsx-transfer-fs-to-gcs-checkpoint.json
```

`--destination-kind` defaults to `auto`, so any destination beginning with `gs://` is treated as GCS. GCS transfers require credentials discoverable by `google-cloud-storage`, such as Application Default Credentials, `GOOGLE_APPLICATION_CREDENTIALS`, or workload identity.

For a local demo:

```bash
gcloud auth application-default login
```

Or use a service account key:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

DSX-Transfer creates the GCS client before scanning so missing credentials fail fast instead of scanning every file and failing each allowed write.

For source-tree runs, use:

```bash
PYTHONPATH=dsx_transfer:dsxa_sdk_py ./.venv/bin/python -m dsx_transfer.cli migrate \
  --source /mnt/source-share \
  --destination gs://customer-clean-bucket/archive \
  --transfer-id fs-to-gcs-demo \
  --scanner-mode dsxa \
  --dsxa-base-url https://scanner.example.com
```

Run the decision service:

```bash
dsx-transfer serve \
  --host 127.0.0.1 \
  --port 8088 \
  --policy-id local-sftpgo-demo \
  --verdict /inbox/bad.exe=malicious \
  --file-type /inbox/payload.bin=PE32FileType \
  --file-type-action windows_executables=block \
  --audit-jsonl /tmp/dsx-transfer-sftpgo-audit.jsonl
```

Run the decision service with DSXA:

```bash
PYTHONPATH=dsx_transfer ./.venv/bin/python -m dsx_transfer.cli serve \
  --host 0.0.0.0 \
  --port 8088 \
  --policy-id dsxa-sftpgo-demo \
  --scanner-mode dsxa \
  --dsxa-base-url https://scanner.example.com \
  --dsxa-auth-token "$DSXA_AUTH_TOKEN" \
  --file-type-action windows_executables=block \
  --audit-jsonl /tmp/dsx-transfer-sftpgo-audit.jsonl
```

For the SFTPGo Docker demo with DSXA scanning:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up --build
```

Use this mode for EICAR/content-verdict demos. The default compose file uses the static scanner and only proves hook and policy behavior.

DSXA stream mode shape:

```bash
dsx-transfer migrate \
  --source ~/Documents/SAMPLES/0Simple \
  --destination ~/Documents/dsx-transfer/dests \
  --transfer-id local-demo \
  --policy-id block-malicious \
  --scanner-mode dsxa \
  --dsxa-base-url https://scanner.example.com \
  --dsxa-auth-token "$DSXA_AUTH_TOKEN"
```

## Docs

- [What This Is](what-this-is.md)
- [Product Modes and Diagrams](product-modes-and-diagrams.md)
- [Architecture](architecture.md)
- [Scanner and Policy](scanner-and-policy.md)
- [Audit and Checkpointing](audit-and-checkpointing.md)
- [Transfer Platform Integrations](integrations.md)
- [SFTPGo Exemplar](sftpgo-exemplar.md)
- [SFTPGo DSXA Demo Complete](sftpgo-demo-complete.md)
- [Transfer Platform Adapters](transfer-platform-adapters.md)
- [Roadmap](roadmap.md)
