# SFTPGo DSXA Demo Complete

This demo shows DSX-Transfer acting as a security enforcement sidecar for SFTPGo.

## What It Demonstrates

```text
SFTPGo Web Client upload
  -> SFTPGo synchronous upload hook
  -> DSX-Transfer decision service
  -> DSXA stream scan
  -> policy decision
  -> allow, or remove and audit blocked file
```

The SFTPGo integration uses the synchronous `upload` hook. SFTPGo writes the file first, then calls DSX-Transfer. DSX-Transfer reads the uploaded bytes from the shared Docker volume, sends them to DSXA, evaluates policy, and removes blocked files immediately.

This is a practical sidecar enforcement demo. It is not the same as a byte-bearing pre-commit hook, because SFTPGo has already written the file when the hook runs.

## Run Command

Start DSXA separately, then run:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml up --build
```

Use `host.docker.internal` when DSXA is running on the host from Docker Desktop. If DSXA is another container or service on the same network, set `DSXA_BASE_URL` to that service URL.

If DSXA requires auth:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
DSXA_AUTH_TOKEN="$DSXA_AUTH_TOKEN" \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml up --build
```

## Demo Login

SFTPGo Admin:

```text
http://127.0.0.1:8080/web/admin
admin / admin-password
```

Create a Web Client user:

```text
username: demo
password: demo-password
home: /srv/sftpgo/data/demo
permissions: all on /
```

SFTPGo Web Client:

```text
http://127.0.0.1:8080/web/client
demo / demo-password
```

## Expected Behavior

Upload a batch containing benign files and EICAR.

Expected result:

- Benign files remain uploaded.
- EICAR is removed after DSXA returns a malicious verdict.
- The Web Client continues the multi-file batch after the malicious file.
- DSX-Transfer writes one JSONL audit event per hook decision.

Audit path inside the sidecar/shared volume:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml exec dsx-transfer \
  tail -n 20 /srv/sftpgo/dsx-transfer-audit.jsonl
```

## Demo Policy Choices

The DSXA demo entrypoint uses:

```bash
--scanner-mode dsxa
--file-type-action windows_executables=block
--verdict-action unknown=allow
--sftpgo-block-response allow_after_remove
```

`unknown=allow` keeps the demo focused on known malicious detections instead of blocking every file DSXA cannot classify confidently.

`allow_after_remove` exists because SFTPGo Web Client can stop a multi-file batch when one hook returns `403`. In this mode, DSX-Transfer still removes and audits blocked files, but returns HTTP `200` to SFTPGo so the rest of the batch continues.

For strict per-file failure semantics, run the service with:

```bash
--sftpgo-block-response reject
```

## Verified State

The focused package test command passes:

```bash
PYTHONPATH=dsx_transfer ./.venv/bin/python -m pytest dsx_transfer/tests
```

Last verified result:

```text
40 passed
```
