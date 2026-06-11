# SFTPGo Exemplar

SFTPGo is the preferred first exemplar for DSX-Transfer MFT-style integration.

It is not a MOVEit-class enterprise MFT platform, but it is a strong engineering proving ground because it is open source, Docker-friendly, supports common transfer protocols, has multiple storage backends, and exposes an event/action model that can be used to test pre-commit enforcement.

## Why SFTPGo First

SFTPGo gives DSX-Transfer a realistic transfer-platform integration without requiring commercial licensing.

Useful traits:

- local Docker-friendly deployment
- SFTP, FTP/S, HTTP/S, and WebDAV surfaces
- local filesystem, S3, Google Cloud Storage, Azure Blob, SFTP, and HTTP filesystem backends
- users, groups, roles, virtual folders, and quotas
- event manager with HTTP notifications and command execution
- sync pre-events such as pre-upload, pre-download, and pre-delete that can allow or deny operations

This makes it a practical stand-in for the class of integrations we eventually want with MOVEit, GoAnywhere, Sterling, Axway, or similar platforms.

## Integration Model

Ideal model:

```text
SFTPGo pre-upload event
  -> DSX-Transfer policy endpoint / adapter
  -> DSXA stream scan
  -> GuardedTransferPolicy
  -> allow / block decision
  -> SFTPGo allows or denies upload
```

SFTPGo owns:

- transfer protocol
- user/session management
- virtual folders
- storage backend
- operational transfer workflow

DSX-Transfer owns:

- scan request normalization
- DSXA interaction
- verdict and detected-file-type policy
- allow/block/exclude/manual-review decision
- audit event
- future DSX Console visibility

Current code seam:

- `SftpGoTransferPlatformAdapter`
- `SftpGoEventContext`
- `sftpgo_context_from_payload`
- `CommitDecision`

These are intentionally adapter-level contracts first. The HTTP endpoint and container shape can be built on top of them without changing the scan/policy model.

## Can SFTPGo Call DSXA Directly?

Technically, yes, for a narrow proof of concept.

SFTPGo can run commands or call HTTP endpoints from event actions. If an action has access to the uploaded file path or stream context, it could call DSXA directly and fail the action when DSXA returns a non-allowed result.

That direct shape looks like:

```text
SFTPGo pre-upload action
  -> DSXA scan
  -> custom script maps DSXA result to exit code
  -> SFTPGo allow/deny
```

This is useful for a quick spike, but it should not be the product architecture.

## Why DSX-Transfer Should Sit Between SFTPGo and DSXA

DSXA is a scanner. DSX-Transfer is the enforcement layer.

Putting DSX-Transfer between SFTPGo and DSXA gives us:

- stable allow/block contract for transfer platforms
- verdict normalization
- detected DSXA file type policy
- supertype aliases such as `windows_executables`
- audit and checkpoint/event semantics
- DSX Console reporting path
- consistent authentication to DSXA
- consistent error taxonomy
- retry and timeout policy
- future manual-review or quarantine decisions
- product-level policy versioning

Current SFTPGo demo model:

```text
SFTPGo upload event
  -> DSX-Transfer reads uploaded bytes from shared storage
  -> DSXA or static scan gate
  -> GuardedTransferPolicy
  -> allow / block decision
  -> DSX-Transfer removes blocked files
  -> SFTPGo returns success or upload failure to the client
```

The current SFTPGo hook is synchronous and scans real file content, but it is post-write from SFTPGo's storage perspective. That makes it useful for a visible demo and a practical integration spike. It is not the same clean destination guarantee as a true byte-bearing pre-commit hook.

Without DSX-Transfer in the middle, every transfer-platform integration has to reinvent:

- how to call DSXA
- how to interpret verdicts
- how to treat unsupported or unknown files
- how to apply file type rules
- how to record audit
- how to report decisions back to DSX Console
- how to handle scanner errors

That creates one-off scripts instead of a reusable product integration.

## When To Use What

There are three practical integration levels.

### Use SFTPGo -> DSXA Directly

Use this when:

- you are proving that SFTPGo can block uploads
- you only need one local integration
- you are comfortable mapping DSXA verdicts yourself
- you do not need shared policy, audit, or DSX Console reporting yet
- you can tolerate a script or event action that is specific to one deployment

Shape:

```text
SFTPGo event action
  -> DSXA
  -> local script maps verdict/file type to allow or deny
```

Pros:

- fastest proof of concept
- fewest moving parts
- no new service required

Cons:

- policy mapping lives in a script
- audit and reporting are one-off
- every platform integration repeats the same logic
- no stable transfer decision contract
- harder to reuse for MOVEit, GoAnywhere, Sterling, or cloud migration services

### Write A Thin Adapter Over DSXA

Use this when:

- one team needs a reusable internal endpoint
- several SFTPGo rules or deployments need the same verdict mapping
- you want to standardize DSXA response normalization
- you are not ready to introduce the full DSX-Transfer service shape

Shape:

```text
SFTPGo event action
  -> thin DSXA adapter
  -> DSXA
  -> adapter returns allow or deny
```

Pros:

- centralizes DSXA mapping
- easier to reuse than local scripts
- can hide scanner auth and scanner endpoint details

Cons:

- can drift into a private product
- still needs policy, audit, errors, and versioning decisions
- may become another one-off service if the contract is not shared

### Use DSX-Transfer Sidecar / Companion Service

Use this when:

- the integration should be reusable across customers or platforms
- policy should be centrally defined and versioned
- audit events should be durable and visible
- DSX Console reporting matters
- detected DSXA file type rules matter
- you want a contract that can later map to MOVEit, GoAnywhere, Sterling, or cloud migration tools

Shape:

```text
SFTPGo event action
  -> DSX-Transfer decision service
  -> DSXA
  -> GuardedTransferPolicy
  -> audit/reporting
  -> allow or deny
```

Deployment shape:

```text
SFTPGo pod/container
DSXA pod/container
DSX-Transfer decision pod/container
```

The DSX-Transfer decision service can run alongside DSXA as another container or pod. SFTPGo does not need to know DSXA details. It only needs to call a stable transfer decision endpoint.

Pros:

- reusable contract
- shared policy model
- shared verdict and file type normalization
- shared audit/event publishing
- cleaner path to commercial MFT integrations
- scanner authentication and errors are handled consistently

Cons:

- one more service to deploy
- requires product-level API and operational ownership
- more design work than a direct script

## Decision Rule

Use direct DSXA calls for a spike.

Use a thin adapter for a local internal standard.

Use DSX-Transfer as the sidecar/companion service when the integration should become reusable product capability.

## Recommended POC Path

### Step 1: Direct Action Spike

Use SFTPGo's event manager to run a synchronous pre-upload action.

Goal:

- prove that SFTPGo can block an upload based on an external decision
- validate what event fields are available
- validate timing, timeout, and user-facing errors

The action may call a simple local DSX-Transfer decision endpoint or even a temporary script.

### Step 2: DSX-Transfer Decision Endpoint

Add a small DSX-Transfer integration service:

```text
POST /api/v1/transfer-decisions/sftpgo/pre-upload
```

Current local command:

```bash
dsx-transfer serve \
  --host 127.0.0.1 \
  --port 8088 \
  --policy-id local-sftpgo-demo \
  --verdict /inbox/bad.exe=malicious \
  --file-type /inbox/payload.bin=PE32FileType \
  --file-type-action windows_executables=block
```

Request contains:

- SFTPGo event metadata
- user
- virtual path
- filesystem path or stream reference
- file size
- protocol
- transfer ID / event ID

Response contains:

```json
{
  "action": "allow",
  "reason": "verdict_rule:benign",
  "policy_id": "default-transfer-policy",
  "scan_guid": "scan-123",
  "file_type": "PDFFileType"
}
```

### Local End-To-End Decision Demo

Health check:

```bash
curl -sS http://127.0.0.1:8088/healthz
```

Clean upload decision:

```bash
curl -sS -X POST http://127.0.0.1:8088/api/v1/transfer-decisions/sftpgo/pre-upload \
  -H 'Content-Type: application/json' \
  -d '{"event":{"path":"/inbox/clean.txt","username":"alice"},"content_text":"clean"}'
```

Expected decision:

```json
{
  "action": "allow",
  "reason": "verdict_rule:benign",
  "policy_id": "local-sftpgo-demo",
  "verdict": "benign"
}
```

### Real SFTPGo Hook Demo

The repo includes a local Docker harness:

```text
dsx_transfer/examples/sftpgo/
```

It configures SFTPGo with environment variables:

```yaml
SFTPGO_COMMON__UPLOAD_MODE: "0"
SFTPGO_COMMON__ACTIONS__EXECUTE_ON: "upload"
SFTPGO_COMMON__ACTIONS__EXECUTE_SYNC: "upload"
SFTPGO_COMMON__ACTIONS__HOOK: "http://dsx-transfer:8088/api/v1/sftpgo/hooks/upload"
```

This uses the SFTPGo custom action contract: HTTP `200` allows the operation, and non-`200` fails the hook. `execute_sync=upload` makes SFTPGo wait for the hook result and return an error to the client. DSX-Transfer also removes blocked files from shared storage.

The demo uses `upload_mode=0` so the uploaded file is visible at its final path when the synchronous upload hook runs.

Run the sidecar demo:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up
```

The quick demo runs DSX-Transfer as a sidecar container sharing the same Docker volume as SFTPGo. By default it uses the static demo scanner, which proves hook plumbing and policy mapping but does not perform real content detection.

To run DSXA mode:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up --build
```

Use `host.docker.internal` when DSXA is running on the host from Docker Desktop. If DSXA runs as another service on the same Docker network, set `DSXA_BASE_URL` to that service URL.

The DSXA override runs the `dsx-transfer` service in this shape:

```bash
python -m dsx_transfer.cli serve \
  --host 0.0.0.0 \
  --port 8088 \
  --policy-id dsxa-sftpgo-demo \
  --scanner-mode dsxa \
  --dsxa-base-url "$DSXA_BASE_URL" \
  --dsxa-auth-token "$DSXA_AUTH_TOKEN" \
  --file-type-action windows_executables=block \
  --verdict-action unknown=allow \
  --sftpgo-storage-root /srv/sftpgo \
  --sftpgo-container-root /srv/sftpgo \
  --sftpgo-block-response allow_after_remove \
  --audit-jsonl /srv/sftpgo/dsx-transfer-audit.jsonl
```

The current real-content SFTPGo path is a synchronous `upload` hook with shared storage access. That is post-write from SFTPGo's perspective, but DSX-Transfer removes blocked files immediately after scanning. This is useful for a practical SFTPGo integration, but it is not the same clean pre-commit guarantee as a hook that exposes bytes before commit.

For Web Client batch demos, DSX-Transfer can use `--sftpgo-block-response allow_after_remove`: blocked files are deleted and audited, but the hook returns HTTP `200` so SFTPGo continues the remaining files in a multi-file upload. Use `reject` for stricter per-file transfer failure semantics.

Run SFTPGo:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up
```

The compose file runs SFTPGo in portable mode with:

```text
username: demo
password: demo-password
home directory: /srv/sftpgo inside the container
shared storage: Docker volume `sftpgo-upload-data`
```

Upload:

```text
clean.txt
bad.exe
payload.bin
eicar.txt
```

The example includes an `expect` helper for non-interactive local testing:

```bash
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/dsx-transfer-clean.txt clean.txt
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/dsx-transfer-bad.exe bad.exe
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/dsx-transfer-payload.bin payload.bin
```

Expected:

- `clean.txt` is allowed.
- `bad.exe` is denied by malicious verdict policy.
- `payload.bin` is denied by DSXA file type policy.
- In DSXA mode, EICAR is denied by DSXA's malicious verdict. The default static demo mode does not identify EICAR by content.

Expected result when the storage root is visible to both SFTPGo and DSX-Transfer:

- `clean.txt` uploaded successfully and SFTPGo wrote it to `/srv/sftpgo`.
- `bad.exe` failed in the SFTP client; DSX-Transfer returned HTTP `403` and removed it.
- `payload.bin` failed in the SFTP client; DSX-Transfer returned HTTP `403` and removed it.
- In DSXA mode, EICAR was removed after DSXA returned a malicious verdict.
- The shared SFTPGo volume contained only `clean.txt`.
- The SFTPGo destination contained only `clean.txt`.
- The shared volume contains `dsx-transfer-audit.jsonl` with one `transfer_platform_decision` event per hook decision.

Inspect the sidecar audit stream:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml exec dsx-transfer \
  tail -n 20 /srv/sftpgo/dsx-transfer-audit.jsonl
```

If DSX-Transfer returns HTTP `400` with "uploaded file does not exist", the SFTPGo container's storage path is not visible to the DSX-Transfer process. The upload-hook design requires a shared filesystem or a DSX-Transfer sidecar/container attached to the same volume as SFTPGo.

### SFTPGo UI Demo

For demoing the SFTPGo Web Admin/Web Client, use the UI sidecar compose file:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml up --build
```

For the UI demo with real DSXA scanning:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml up --build
```

Open:

```text
http://127.0.0.1:8080/web/admin
```

Login:

```text
username: admin
password: admin-password
```

The UI demo runs normal SFTPGo server mode, creates the default admin automatically, and runs DSX-Transfer as a sidecar on the same Docker volume. SFTPGo calls:

```text
http://dsx-transfer:8088/api/v1/sftpgo/hooks/upload
```

Use the UI to create a demo SFTP user, then upload the same `clean.txt`, `bad.exe`, and `payload.bin` files to show allow/block behavior from the user's perspective. In DSXA mode, include EICAR to show content-based malicious verdict handling.

The UI demo uses the same sidecar audit path:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml exec dsx-transfer \
  tail -n 20 /srv/sftpgo/dsx-transfer-audit.jsonl
```

Malicious verdict decision:

```bash
curl -sS -X POST http://127.0.0.1:8088/api/v1/transfer-decisions/sftpgo/pre-upload \
  -H 'Content-Type: application/json' \
  -d '{"event":{"path":"/inbox/bad.exe","username":"alice"},"content_text":"malware"}'
```

Expected decision:

```json
{
  "action": "block",
  "reason": "verdict_rule:malicious",
  "policy_id": "local-sftpgo-demo",
  "verdict": "malicious"
}
```

Detected file type decision:

```bash
curl -sS -X POST http://127.0.0.1:8088/api/v1/transfer-decisions/sftpgo/pre-upload \
  -H 'Content-Type: application/json' \
  -d '{"event":{"path":"/inbox/payload.bin","username":"alice"},"content_text":"payload"}'
```

Expected decision:

```json
{
  "action": "block",
  "reason": "file_type_rule:PE32FileType",
  "policy_id": "local-sftpgo-demo",
  "file_type": "PE32FileType",
  "verdict": "benign"
}
```

For blocked files:

```json
{
  "action": "block",
  "reason": "file_type_rule:PE32FileType",
  "policy_id": "block-executables",
  "scan_guid": "scan-456",
  "file_type": "PE32FileType"
}
```

### Step 3: General Transfer Platform Contract

Generalize the endpoint contract so MOVEit, GoAnywhere, Sterling, or other platforms can use the same decision API.

```text
TransferPlatformAdapter
  -> ScanGate
  -> GuardedTransferPolicy
  -> CommitDecision
```

This family of integrations should be modeled as `TransferPlatformAdapter` implementations. See [Transfer Platform Adapters](transfer-platform-adapters.md).

## Product Framing

SFTPGo is not the commercial target. It is the exemplar and proving ground.

```text
Engineering exemplar: SFTPGo
Commercial story: MOVEit / GoAnywhere / Sterling / Axway
```

The SFTPGo work should prove the architecture:

- synchronous transfer-platform enforcement is feasible
- DSX-Transfer can sit between MFT platform and DSXA
- the platform can enforce DSX's decision
- audit and policy records are useful
- the same decision contract can map to future commercial MFT integrations

The remaining open question for SFTPGo specifically is whether a supported extension path can expose upload bytes before final storage commit. If not, SFTPGo remains a strong sidecar/removal demo, while MOVEit, GoAnywhere, Sterling, and cloud migration services should each be evaluated for cleaner pre-commit extension points.
