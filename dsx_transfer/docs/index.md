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
./.venv/bin/python -m pip install -e ./dsx_transfer
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
- [Architecture](architecture.md)
- [Scanner and Policy](scanner-and-policy.md)
- [Audit and Checkpointing](audit-and-checkpointing.md)
- [Transfer Platform Integrations](integrations.md)
- [SFTPGo Exemplar](sftpgo-exemplar.md)
- [SFTPGo DSXA Demo Complete](sftpgo-demo-complete.md)
- [Transfer Platform Adapters](transfer-platform-adapters.md)
- [Roadmap](roadmap.md)
