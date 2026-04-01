# Developer's Guide

This section is for developers integrating DSX scanning into applications and services.

## In this guide

- [DSXA SDK](dsxa-sdk.md)
- [Python SDK calls](sdk/python.md)
- [Swift SDK calls](sdk/swift.md)
- [JavaScript SDK calls](sdk/javascript.md)

## Typical integration patterns

1. Backend service scans files from disk after upload or ingestion.
2. Web/API backend scans upload bytes or streams before persistence.
3. Worker jobs scan files in parallel with bounded concurrency.

## Design goals

- Reuse SDK clients/sessions for connection pooling efficiency.
- Keep concurrency in the application layer (bounded and observable).
- Standardize request headers, auth, and error handling through SDKs.
