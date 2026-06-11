# SFTPGo Local Hook Demo

This example runs a real SFTPGo container and points its synchronous `upload` hook at the local DSX-Transfer decision service.

SFTPGo behavior used here:

- `upload` HTTP hooks run after SFTPGo writes the uploaded file.
- HTTP status `200` allows the completed upload to stand.
- Any non-`200` response fails the hook. DSX-Transfer also removes blocked files.
- The hook body contains transfer metadata such as `action`, `username`, `path`, `virtual_path`, `file_size`, `protocol`, and `session_id`.

The quick demo runs DSX-Transfer as a sidecar container in the same compose stack as SFTPGo. Both services mount the same Docker volume at `/srv/sftpgo`, so DSX-Transfer can read uploaded bytes reliably.

The default compose file uses the static demo scanner. It proves hook plumbing and DSX-Transfer policy mapping, but it does not perform real content detection. EICAR and other content-based detections require DSXA mode.

For DSXA mode, set `DSXA_BASE_URL` and rebuild the sidecar:

```bash
DSXA_BASE_URL=http://host.docker.internal:15000 \
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up --build
```

Use `host.docker.internal` when DSXA is running on the host from Docker Desktop. If DSXA is another compose service or container on the same Docker network, set `DSXA_BASE_URL` to that service URL.

The override runs DSX-Transfer in this shape:

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

The SFTPGo `upload` hook gives DSX-Transfer a real file path. DSX-Transfer reads the uploaded bytes from the shared volume, streams them to the configured scanner, and removes the file when policy blocks it.

The DSXA demo entrypoint uses `--sftpgo-block-response allow_after_remove`. That means blocked files are deleted and audited, but DSX-Transfer returns HTTP `200` to SFTPGo so the Web Client can continue a multi-file batch after one malicious file. Use `--sftpgo-block-response reject` when you want SFTPGo to fail the individual upload with a non-`200` hook response.

Start the quick portable SFTPGo demo:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml up
```

The compose file configures SFTPGo with environment variables:

```yaml
SFTPGO_COMMON__UPLOAD_MODE: "0"
SFTPGO_COMMON__ACTIONS__EXECUTE_ON: "upload"
SFTPGO_COMMON__ACTIONS__EXECUTE_SYNC: "upload"
SFTPGO_COMMON__ACTIONS__HOOK: "http://dsx-transfer:8088/api/v1/sftpgo/hooks/upload"
```

The demo uses `upload_mode=0` so the uploaded file is visible at its final path when the synchronous upload hook runs.

The compose file runs SFTPGo in portable mode with a scripted SFTP user:

```text
username: demo
password: demo-password
home directory: /srv/sftpgo inside the container
shared storage: Docker volume `sftpgo-upload-data`
```

Test with SFTP manually:

```bash
printf 'clean\n' > /tmp/clean.txt
printf 'malware\n' > /tmp/bad.exe
printf 'payload\n' > /tmp/payload.bin

sftp -P 2022 demo@127.0.0.1
```

For DSXA mode, also upload the EICAR antivirus test file. DSXA should return a malicious verdict and DSX-Transfer should remove it.

Inside the SFTP prompt:

```text
put /tmp/clean.txt clean.txt
put /tmp/bad.exe bad.exe
put /tmp/payload.bin payload.bin
```

Or use the included expect helper:

```bash
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/clean.txt clean.txt
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/bad.exe bad.exe
expect dsx_transfer/examples/sftpgo/sftp_put.expect /tmp/payload.bin payload.bin
```

Expected result:

- `clean.txt` is allowed.
- `bad.exe` is denied because DSX-Transfer returns `403` for `verdict_rule:malicious`.
- `payload.bin` is denied because DSX-Transfer returns `403` for `file_type_rule:PE32FileType`.
- In DSXA mode, EICAR is denied by DSXA's malicious verdict.

Expected behavior:

- Allowed upload: SFTP client reports success and SFTPGo writes `clean.txt`.
- Blocked uploads: SFTP client reports failure and DSX-Transfer logs HTTP `403 Forbidden`.
- Destination contents: only `clean.txt`.
- Audit: `/srv/sftpgo/dsx-transfer-audit.jsonl` contains one `transfer_platform_decision` JSONL event per hook decision.

Verified sidecar behavior:

- `clean.txt` uploaded successfully.
- `bad.exe` failed with `close remote: Failure`; DSX-Transfer returned HTTP `403`.
- `payload.bin` failed with `close remote: Failure`; DSX-Transfer returned HTTP `403`.
- The shared SFTPGo volume contained only `clean.txt`.
- The shared SFTPGo volume contained `dsx-transfer-audit.jsonl` with allow/block decisions.

Inspect audit output:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.yml exec dsx-transfer \
  tail -n 20 /srv/sftpgo/dsx-transfer-audit.jsonl
```

If DSX-Transfer returns `400` with "uploaded file does not exist", the SFTPGo storage path is not visible to the DSX-Transfer process. In this sidecar compose demo, both services share the same Docker volume at `/srv/sftpgo`.

## UI Demo

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

The UI demo runs normal SFTPGo server mode, creates the default admin automatically, and runs DSX-Transfer as a sidecar on the same Docker volume.

The SFTPGo hook is:

```text
http://dsx-transfer:8088/api/v1/sftpgo/hooks/upload
```

To create an SFTP user from the UI:

- Go to `Users`.
- Add user `demo`.
- Set password `demo-password`.
- Use local filesystem storage.
- Set home directory under `/srv/sftpgo/data/demo`.
- Grant permissions for `/`.

Then open the Web Client:

```text
http://127.0.0.1:8080/web/client
```

Login as:

```text
demo / demo-password
```

Upload these files through the browser:

```bash
printf 'clean\n' > /tmp/clean.txt
printf 'malware\n' > /tmp/bad.exe
printf 'payload\n' > /tmp/payload.bin
```

In DSXA mode, include the EICAR antivirus test file. The default static mode will not identify EICAR by content.

Expected UI result:

- `clean.txt` remains uploaded.
- `bad.exe` upload fails or disappears after the hook blocks it.
- `payload.bin` upload fails or disappears after the hook blocks it.
- In DSXA mode, EICAR disappears after DSXA returns a malicious verdict.
- With the demo's `allow_after_remove` response mode, the Web Client can continue uploading the other files in the batch.
- `dsx-transfer-audit.jsonl` records the hook decision for each uploaded file.

Inspect UI demo audit output:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml exec dsx-transfer \
  tail -n 20 /srv/sftpgo/dsx-transfer-audit.jsonl
```

Stop the UI demo:

```bash
docker compose -f dsx_transfer/examples/sftpgo/docker-compose.ui.yml down
```

Important limitation:

This `upload` hook path is post-write from SFTPGo's perspective. DSX-Transfer scans immediately and removes blocked files, but this is not the same clean pre-commit guarantee as a hook that exposes bytes before destination commit.
