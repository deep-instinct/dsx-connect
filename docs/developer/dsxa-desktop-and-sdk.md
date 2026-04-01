# DSXA Desktop and SDK

This section covers the local DSXA Desktop app and the SDKs used to integrate DSXA scanning into applications and services.

## Components

- **DSXA Desktop**
  - Local desktop client for manual file, folder, and hash scanning
  - Source: `dsxa_desktop/`
- **Python SDK**
  - Sync and async clients, including streaming support
  - Source: `dsxa_sdk_py/`
- **JavaScript SDK**
  - Node.js and browser client surface for DSXA APIs
  - Source: `dsxa_sdk_js/`
- **Swift SDK**
  - Native client support for Apple platform integrations

## DSXA Desktop Quick Start

### 1. Create a connection

When you first open DSXA Desktop, create or select a connection profile and fill in:

- **Base URL**
  - Example: `http://127.0.0.1:15000`
- **Auth token**
  - Leave empty if your scanner does not require one
- **Protected entity**
  - Usually `1` unless your environment uses a different value
- **Custom metadata**
  - Optional; may be used to tag scans
- **Verify TLS**
  - Enable for proper HTTPS validation
  - Disable only for local development or self-signed test environments

Use **New Connection** to create a profile, then save it before scanning.

### 2. Test scanner connectivity

Before scanning a real file:

- confirm the scanner URL is reachable
- verify auth settings
- verify the scanner is not still initializing

The Desktop UI shows readiness state for the configured scanner. If the scanner is unreachable or misconfigured, fix that before proceeding.

### 3. Run an EICAR test

Use the built-in **EICAR** test to confirm the end-to-end path is working:

- DSXA Desktop can reach the scanner
- the scanner returns a verdict
- the current connection profile is valid

This is the quickest safe validation before running real file or folder scans.

### 4. Scan a single file

Use **Scan File** when you want to validate one file quickly:

- choose the target file
- optionally set password or metadata overrides
- start the scan

This is useful for spot checks and troubleshooting metadata, protected entity, or auth issues.

### 5. Scan a folder

Use **Scan Folder** for multi-file benchmarking or validation:

- choose the folder
- set a file pattern if needed
- choose **Max Concurrent Scans**
- optionally enable detailed JSONL or malicious-only CSV logging

Folder scan output includes:

- total scanned files
- elapsed time
- DSXA scan time sum
- verdict counts
- failures

### 6. Scan a hash

Use **Scan Hash** when you want to query by file hash instead of uploading bytes.

This is useful for reputation-style checks or when the file content is not available locally.

## DSXA Desktop Notes

- Desktop now streams binary file uploads instead of buffering entire files before sending them.
- Folder scan concurrency is caller-controlled and should be increased gradually.
- Very large files may be better suited to scan-by-path workflows when supported by the deployment.
- Base64 mode is available, but binary mode is generally preferable for throughput.

## Common Desktop Workflow

1. Create a new connection profile.
2. Enter scanner URL and optional auth token.
3. Verify the scanner is reachable.
4. Run the EICAR test.
5. Scan a single known-good file.
6. Run a folder scan with bounded concurrency.
7. Export JSONL or CSV logs if you need detailed review.

## SDK Guides

- [DSXA SDK overview](dsxa-sdk.md)
- [Python SDK calls](sdk/python.md)
- [Swift SDK calls](sdk/swift.md)
- [JavaScript SDK calls](sdk/javascript.md)

## Key points

1. SDK clients handle request construction, auth headers, connection reuse, and response parsing.
2. Concurrency is typically managed by the caller, not by a single DSXA batch endpoint.
3. Streaming matters for throughput and memory usage, especially for large files or local desktop scanning workflows.
4. DSXA Desktop is useful for local validation and manual workflows, while the SDKs are the integration path for services and apps.

## Typical SDK usage patterns

1. Scan files already on disk.
2. Scan upload bytes or streams inside a backend service.
3. Run bounded concurrent scans across a folder or queue.
4. Use scan-by-path when the scanner can access the target path directly.
