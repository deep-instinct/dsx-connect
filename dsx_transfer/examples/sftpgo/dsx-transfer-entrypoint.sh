#!/bin/sh
set -eu

if [ -n "${DSXA_BASE_URL:-}" ]; then
  exec python -m dsx_transfer.cli serve \
    --host 0.0.0.0 \
    --port 8088 \
    --policy-id dsxa-sftpgo-demo \
    --scanner-mode dsxa \
    --dsxa-base-url "$DSXA_BASE_URL" \
    --dsxa-auth-token "${DSXA_AUTH_TOKEN:-}" \
    --file-type-action windows_executables=block \
    --verdict-action unknown=allow \
    --sftpgo-storage-root /srv/sftpgo \
    --sftpgo-container-root /srv/sftpgo \
    --sftpgo-block-response allow_after_remove \
    --audit-jsonl /srv/sftpgo/dsx-transfer-audit.jsonl
fi

exec python -m dsx_transfer.cli serve \
  --host 0.0.0.0 \
  --port 8088 \
  --policy-id sftpgo-upload-demo \
  --verdict /bad.exe=malicious \
  --file-type /payload.bin=PE32FileType \
  --file-type-action windows_executables=block \
  --sftpgo-storage-root /srv/sftpgo \
  --sftpgo-container-root /srv/sftpgo \
  --audit-jsonl /srv/sftpgo/dsx-transfer-audit.jsonl
