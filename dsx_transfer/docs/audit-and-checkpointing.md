# Audit and Checkpointing

Guarded Transfer keeps audit and checkpoint state separate.

## Audit

The audit log records what happened. The current implementation writes JSONL through `JsonLinesAuditSink`.

Each item outcome emits an event:

```json
{
  "event_type": "transfer_item_outcome",
  "transfer_id": "local-demo",
  "object_identity": "bad.exe",
  "state": "blocked",
  "verdict": "malicious",
  "action": "block",
  "policy_id": "block-malicious",
  "bytes_written": 0
}
```

Transfer platform hooks emit the same JSONL stream with `event_type` set to `transfer_platform_decision`:

```json
{
  "event_type": "transfer_platform_decision",
  "transfer_id": "session-1",
  "object_identity": "/bad.exe",
  "state": "blocked",
  "verdict": "malicious",
  "action": "block",
  "policy_id": "sftpgo-upload-demo",
  "bytes_written": 7,
  "transfer_platform": "sftpgo",
  "platform_event_type": "upload",
  "user_id": "demo"
}
```

Use audit for:

- reporting
- troubleshooting
- DSX Console-style visibility
- proving which files were allowed, blocked, skipped, or failed
- later publishing to a central event system

## Checkpoint

The checkpoint records operational resume state. The current implementation writes JSON through `JsonCheckpointStore`.

The engine reads checkpoint state on rerun. If a file was previously `allowed` and the source fingerprint still matches, the rerun marks the item `skipped` instead of scanning and copying again.

Use checkpoint for:

- resumability
- avoiding duplicate destination writes
- preserving progress after interruption
- retrying failed migrations without recopying completed items

## Distinction

```text
audit.jsonl      = historical event log
checkpoint.json  = operational resume state
```
