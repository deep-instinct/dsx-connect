# DSXA SDK

This section covers the SDKs used to integrate DSXA scanning into applications and services.

For the DSXA Desktop app quick start and install notes, see [Resources > DSXA Desktop](../resources/dsxa-desktop.md).

## SDK Guides

- [DSXA SDK overview](dsxa-sdk.md)
- [Python SDK calls](sdk/python.md)
- [Swift SDK calls](sdk/swift.md)
- [JavaScript SDK calls](sdk/javascript.md)

## Key Points

1. SDK clients handle request construction, auth headers, connection reuse, and response parsing.
2. Concurrency is typically managed by the caller, not by a single DSXA batch endpoint.
3. Streaming matters for throughput and memory usage, especially for large files.
4. The SDKs are the integration path for services, tools, CLIs, and application code.

## Typical SDK usage patterns

1. Scan files already on disk.
2. Scan upload bytes or streams inside a backend service.
3. Run bounded concurrent scans across a folder or queue.
4. Use scan-by-path when the scanner can access the target path directly.
