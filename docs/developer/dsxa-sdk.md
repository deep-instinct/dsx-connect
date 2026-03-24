# DSXA SDK: Concurrency, Batching, and Throughput

This page clarifies where concurrency lives when using the DSXA SDKs, and how to get high throughput safely.

## Language references

- [Python SDK calls](sdk/python.md)
- [Swift SDK calls](sdk/swift.md)
- [JavaScript SDK calls](sdk/javascript.md)

## Primary use cases

1. Scan a file that already exists on disk.
2. Scan file bytes/streams received by your backend during upload handling.
3. Scan many files concurrently from a queue or folder walk with bounded workers.

## Quick answer

The Python and Swift SDKs do **not** currently expose a single "batch scan" API endpoint.

- The SDK clients provide **single-request scan operations** (`scan_file`, `scan_binary`, `scan_by_path`, etc.).
- **Concurrent scanning is implemented by the caller** (CLI, GUI, or your application) by running many scan calls in parallel.

In other words:

- SDK: request construction, transport/session management, auth headers, response parsing, error mapping.
- Caller: work queue, concurrency limit, retries/backoff policy, cancellation strategy.

## Where concurrency is handled today

### Python

- SDK client: `DSXAClient` / `AsyncDSXAClient`
  - Single-item APIs
  - Shared `httpx.Client` / `httpx.AsyncClient` per client instance
- CLI/GUI:
  - `scan-folder` / `scan-files` use async semaphore-based fan-out
  - GUI folder scans use bounded thread pools

### Swift

- SDK client: `DSXAClient`
  - Single-item async APIs
  - Shared `URLSession` pool (`SessionPool.secure` / `SessionPool.insecure`)
- GUI:
  - Folder scans run with a bounded `TaskGroup` fan-out

## Why use the SDK (instead of ad-hoc HTTP)

Using the SDK still gives important performance and reliability benefits:

1. Connection pool reuse
- Python: one `httpx` client reused across scans.
- Swift: shared `URLSession` instances with configured max host connections.
- Benefit: lower handshake/setup overhead, better sustained throughput.

2. Consistent request headers
- Handles `AUTH`/`AUTH_TOKEN`, metadata, protected entity, password encoding.
- Benefit: fewer subtle integration bugs.

3. Typed responses and normalized errors
- Structured response models and centralized HTTP error mapping.
- Benefit: simpler caller code and better diagnostics.

4. Streaming support (Python)
- `scan_binary_stream` avoids loading whole file bytes into memory first.
- Benefit: lower peak memory and better large-file behavior.

5. Shared behavior across tools
- CLI, GUI, and custom apps can all rely on the same transport/auth semantics.
- Benefit: easier debugging and parity across environments.

## Usage patterns

### Pattern A: File on disk

Use SDK convenience helpers (`scan_file` / `scanFile`) for straightforward local-file scanning.

### Pattern B: Upload data in a web backend

For web/API services receiving file uploads:

- Prefer scanning bytes/streams in backend code before storing.
- Use streaming APIs where available (Python: `scan_binary_stream`) to reduce peak memory.
- Keep frontend clients from calling DSXA directly in most production architectures; centralize auth and policy in your backend service.

### Pattern C: Parallel scans

Use SDK client calls inside a bounded worker model:

- Python: `asyncio` + semaphore, or thread pool for sync workflows.
- Swift: `TaskGroup` with explicit max in-flight tasks.

## Best practices for high throughput

1. Reuse one client instance
- Do not create a new SDK client per file.
- Create once per scan run, close at the end.

2. Use bounded concurrency
- Start with `4-8` workers (or lower on constrained hosts).
- Increase gradually while monitoring DSXA latency/error rate.

3. Avoid unbounded fan-out
- Use semaphores/task groups/thread pools with explicit limits.
- This prevents local resource exhaustion and DSXA overload.

4. Prefer streaming for large files (Python)
- Use `scan_binary_stream` with chunked reads.

5. Add retry/backoff only for transient failures
- Retry connection resets/timeouts/5xx.
- Do not blindly retry 4xx auth/validation errors.

6. Keep file IO and network balanced
- If reads are slow, extra HTTP concurrency will not help.
- Profile disk/network bottlenecks before raising concurrency further.

## Example architecture

Typical high-throughput pattern in both languages:

1. Enumerate file paths.
2. Push paths into a bounded worker fan-out.
3. Each worker calls SDK scan APIs.
4. Aggregate results and failures.
5. Emit summary metrics (elapsed time, per-file scan time, p50/p95, errors).

## Future enhancement direction

If desired, a helper can be added in each SDK (for example `scan_folder(...)`) that wraps:

- enumeration
- bounded concurrency
- optional retry policy
- summary stats

This would provide a standard batching utility while still using the current DSXA per-file scan endpoints.

## JavaScript SDK direction

A JavaScript/TypeScript SDK is a valid next step for web-backend and Node.js workflows.

Suggested initial scope:

1. `scanBinary` (Buffer/Uint8Array)
2. `scanStream` (Node.js Readable stream)
3. `scanByPath` and polling helpers
4. Shared auth/header helpers and typed response models
5. Error mapping aligned with Python/Swift SDK semantics
