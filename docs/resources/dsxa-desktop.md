# DSXA Desktop

DSXA Desktop is the local desktop client for manual file, folder, hash, and EICAR scanning against a DSXA scanner.

- [DSXA Desktop Releases](https://github.com/deep-instinct/dsx-connect/releases?q=dsxa-desktop&expanded=true)

## Quick Start

### 1. Create a connection

When you first open DSXA Desktop, create or select a connection profile and fill in:

- **Base URL**
  - Example: `http://127.0.0.1:15000`
  - Do not include the API path such as `/scan/binary/v2`
- **Auth token**
  - Leave empty if your scanner does not require one
- **Protected entity**
  - Defaults to `1`
- **Custom metadata**
  - Optional
- **Verify TLS**
  - Enable for proper HTTPS validation
  - Disable only for local development or self-signed test environments

Use **New Connection** to create a profile, then save it before scanning.

### 2. Test scanner connectivity

Before scanning a real file:

- confirm the scanner URL is reachable
- verify auth settings
- verify the scanner is not still initializing

The Desktop UI shows readiness state for the configured scanner.

### 3. Run an EICAR test

Use the built-in **EICAR** test to confirm:

- DSXA Desktop can reach the scanner
- the scanner returns a verdict
- the current connection profile is valid

### 4. Scan a single file

Use **Scan File** when you want to validate one file quickly:

- choose the target file
- optionally set password or metadata overrides
- start the scan

### 5. Scan a folder

Use **Scan Folder** for multi-file benchmarking or validation:

- choose the folder
- set a file pattern if needed
- choose **Max Concurrent Scans**
- optionally enable detailed JSONL or malicious-only CSV logging

Folder scan output includes:

- max concurrent scans used
- total scanned files
- elapsed time
- DSXA scan time sum
- verdict counts
- failures

### 6. Scan a hash

Use **Scan Hash** when you want to query by file hash instead of uploading bytes.

Note: DSXA must be configured to support hash scanning.

## Common Desktop Workflow

1. Create a new connection profile.
2. Enter scanner URL and optional auth token.
3. Verify the scanner is reachable.
4. Run the EICAR test.
5. Scan a single known-good file.
6. Run a folder scan with bounded concurrency.
7. Export JSONL or CSV logs if you need detailed review.

## Notes

- Desktop streams binary file uploads instead of buffering entire files before sending them.
- Folder scan concurrency is caller-controlled and should be increased gradually.
- Very large files may be better suited to scan-by-path workflows when supported by the deployment.
- Base64 mode is available, but binary mode is generally preferable for throughput.

## macOS Install Note

Unsigned or unnotarized macOS builds may be blocked by Gatekeeper with a message like:

```text
"DSXA Desktop" is damaged and can't be opened. You should move it to the Trash.
```

For local or internal use, first try opening the app from Finder:

1. Right-click `DSXA Desktop.app`
2. Choose `Open`
3. In the macOS warning dialog, click `Open` again

If macOS still refuses to open the app, the usual workaround is to remove the browser quarantine attribute after unzipping:

```bash
xattr -dr com.apple.quarantine "/path/to/DSXA Desktop.app"
```

For normal end-user distribution, the proper fix is to sign and notarize the app with an Apple Developer account.

## Windows Install Note

Unsigned Windows installers may show `Unknown Publisher` during installation. For local or internal use, users can usually continue anyway if they trust the source of the MSI or EXE.

For normal end-user distribution, the proper fix is to sign the Windows installer with a code-signing certificate so Windows can show a verified publisher instead of `Unknown Publisher`.

## SDKs

For DSXA SDK usage and example code, see the Development section:

- [DSXA SDK Overview](../developer/dsxa-sdk.md)
- [Python SDK Calls](../developer/sdk/python.md)
- [Swift SDK Calls](../developer/sdk/swift.md)
- [JavaScript SDK Calls](../developer/sdk/javascript.md)
