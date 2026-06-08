# Reader Contract Model

## Purpose

This document defines the Reader contract used by generic workers to obtain content for scanning and later-stage reuse.

The Reader contract is intentionally independent of whether content is obtained:

- directly from the repository by a native Reader
- indirectly through a connector-owned read capability by a ConnectorProxyReader
- from a cached or quarantine source

The scan worker depends on this contract, not on repository-specific logic.
Later stage workers may also depend on the same contract when content must be re-read from cached or quarantine sources.

---

## Design Principles

- workers stay generic
- Readers own content acquisition only
- connectors remain integration/control-plane components
- proxy and native Readers must produce equivalent semantics
- read failures must be categorized for retry behavior

---

## Reader Roles

### Native Reader

A native Reader is a worker-hosted implementation that directly accesses a repository using repository SDKs or APIs.

Examples:

- `S3NativeReader`
- `SharePointNativeReader`
- `AzureBlobNativeReader`

### ConnectorProxyReader

A ConnectorProxyReader is a generic worker-side Reader that calls a connector-owned read capability over a stable contract.

This preserves the first-generation extensibility model:

- connectors can still be built and released independently of core
- third parties can support platforms without shipping code inside worker runtimes
- DI can later replace selected proxy paths with native Readers for performance

### CachedArtifactReader

A CachedArtifactReader is a worker-side Reader that obtains content from a previously preserved artifact rather than the original repository.

This supports cases where:

- DIANNA should not re-read the original repository object
- later analysis should use the exact bytes scanned earlier
- remediation has moved content to a different location but later stages still need access

### QuarantineReader

A QuarantineReader obtains content from a normalized quarantine or preserved-remediation location.

This allows post-remediation or later-stage validation to remain Reader-driven rather than embedding repository-specific follow-up logic inside workers.

---

## Worker-Side Reader Contract

The scan worker resolves a Reader using integration metadata and read strategy, then invokes:

```python
ReadResult = await reader.acquire(scan_request)
```

The Reader returns enough information for the scan worker to scan content, such as:

- local path
- buffered bytes
- stream handle
- read metadata

The current implementation only supports a local-path result for the first native Reader.

---

## Reader Request Shape

The request to a Reader should be derived from the scan job item and should include:

- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `content_source`
- `read_hint`
- `scan_options`

This is already represented in `scan_item_requested`.

### Semantics

- `object_identity`
  - stable domain identifier for the object
  - may or may not be a direct fetch path

- `content_source`
  - where content may currently be obtained
  - examples:
    - `original`
    - `quarantine`
    - `cached`
    - `none`

- `read_hint`
  - connector- or orchestration-provided read hints
  - enough information to avoid hidden connector-side assumptions

- `scan_options`
  - scan-specific parameters such as protected entity or password
  - also carries operator/API item payload fields that affect how the reader fetches content

---

## Proxy Reader Path Normalization

The connector proxy reader bridges NG scan jobs to connector `read_file` handlers. Batch item payload fields are preserved in `scan_options`, so reader-relevant path aliases must be treated as first-class read inputs.

Accepted path aliases, in priority order within each source:

- `path`
- `file_path`
- `filePath`
- `local_path`
- `localPath`
- `selector`
- `location`

Path resolution order for the legacy connector `read_file` payload is:

1. `read_hint.location` or the first path alias in `read_hint`
2. `scan_options.location` or the first path alias in `scan_options`
3. `content_source.locator`
4. `object_identity`

The resulting value becomes the legacy connector payload `location`.

Connector examples:

- Filesystem: `location` is a local filesystem path, for example `/tmp/dsx-connect-ng/proxy-reader-sample.txt`
- GCS: `location` is the object key inside the configured bucket, for example `BadMojoResume` or `folder/BadMojoResume`

The legacy payload also includes:

- `metainfo`: `read_hint.metainfo`, object identity hints, the resolved location, then `object_identity`
- `size_in_bytes`: optional size hint from `read_hint` or `scan_options`
- `scan_job_id`: the NG job id

---

## Reader Result Shape

The Reader returns a normalized result with one or more of:

- `local_path`
- `byte_stream`
- `content_length`
- `content_type`
- `etag`
- `version`
- `details`

For the current phase, the implemented shape is:

- `local_path`
- `content_length`
- `cleanup_local_path`
- `details`

`cleanup_local_path` defines ownership. When `true`, the scan worker owns the staged file and must delete it after the scan attempt finishes, including scanner failure and post-read oversize rejection. Local, cached, and connector local-stub artifacts remain non-owned and must not be deleted by the worker.

---

## Content Preservation and Reuse

The Reader abstraction is also the intended boundary for content reuse.

Workers should not contain special logic such as:

- "cache the file here because DIANNA might need it"
- "re-open the scan worker's temp file from another stage"

Instead:

- policy/orchestration decides whether later stages require preserved content
- authoritative state updates `content_source` to reflect where later reads should come from
- later workers resolve a Reader again against that updated source

Expected normalized source modes include:

- `original`
- `cached`
- `quarantine`
- `none`

This allows the same stage worker contract to work whether bytes come from:

- the repository
- a connector proxy
- a cached artifact
- a quarantine/preserved location

### Preservation Decision Boundary

Readers do not decide **whether** content should be preserved.

That decision belongs to policy and orchestration.

Readers decide only:

- how bytes are obtained for the current source mode
- how normalized artifact references are dereferenced
- how read failures are categorized

---

## ConnectorProxyReader Contract

When using the proxy strategy, the worker-side Reader calls a connector-owned read capability.

The proxy contract should be stable enough that:

- a third-party connector can implement it without shipping code into the scan worker runtime
- a worker can swap between `proxy` and `native` strategies without changing the scan-stage contract
- retry behavior is driven by normalized error categories rather than connector-specific exceptions

### Request Fields

The connector proxy request should include:

- `job_id`
- `job_item_id`
- `integration_id`
- `scope_id`
- `object_identity`
- `content_source`
- `read_hint`
- `options`
- `preferred_modes`

`preferred_modes` expresses what the worker would like back, in priority order. Example:

- `stream`
- `artifact_ref`
- `buffer`

This lets the connector choose the best supported response mode while keeping worker behavior explicit.

### Request

```json
{
  "job_id": "job-123",
  "job_item_id": "item-456",
  "integration_id": "sharepoint-prod",
  "scope_id": "scope-1",
  "object_identity": "drive:abc/item:def",
  "content_source": {
    "mode": "original",
    "locator": null,
    "details": {}
  },
  "read_hint": {
    "site_id": "s1",
    "drive_id": "d1",
    "item_id": "i1"
  },
  "options": {
    "timeout_seconds": 30
  },
  "preferred_modes": ["stream", "artifact_ref"]
}
```

### Response Fields

The proxy response should include:

- `mode`
- `content_length`
- `content_type`
- `etag`
- `version`
- `artifact_ref` when `mode = artifact_ref`
- `details`

If `mode = stream`, the binary content is the response body.
If `mode = buffer`, the binary content is an in-memory or buffered payload.
If `mode = artifact_ref`, the response contains a temporary artifact descriptor the worker can dereference.

### Response

```json
{
  "mode": "artifact_ref",
  "content_length": 12345,
  "content_type": "application/pdf",
  "etag": "etag-1",
  "version": "7",
  "artifact_ref": {
    "kind": "signed_url",
    "locator": "https://example.invalid/tmp/object-1",
    "expires_at": "2026-05-20T22:00:00Z"
  },
  "details": {
    "source": "connector_proxy"
  }
}
```

The binary content itself may be returned:

- as an HTTP streaming response body
- as a temporary object URL
- as a temporary local cache artifact reference

The transport choice is implementation-specific, but the semantics must be stable from the scan worker’s perspective.

---

## Error Contract

Reader failures should be normalized into categories such as:

- `auth_error`
- `permission_error`
- `object_not_found`
- `rate_limit`
- `transient_platform_error`
- `content_unavailable`
- `invalid_read_context`
- `unsupported_response_mode`

Retry semantics should be driven by category, not raw exception text.

Suggested normalized error payload:

```json
{
  "code": "rate_limit",
  "message": "connector rate limit exceeded",
  "retryable": true,
  "details": {
    "platform_status": 429
  }
}
```

Suggested behavior:

- `object_not_found`
  - terminal
- `content_unavailable`
  - terminal unless source is expected to appear later
- `invalid_read_context`
  - terminal
- `auth_error`
  - usually terminal until credentials change
- `rate_limit`
  - retryable
- `transient_platform_error`
  - retryable
- `unsupported_response_mode`
  - terminal unless the worker retries with a different strategy

---

## Reader Selection

Reader resolution should be explicit and configurable.

Candidate strategies:

- `proxy`
- `native`
- `cached`
- `quarantine`

Per integration, the platform may express:

- preferred strategy
- allowed fallback strategy
- whether native and proxy implementations both exist

Example:

- default third-party path: `proxy`
- DI optimized path: `native`
- post-remediation DIANNA path: `quarantine`

### Integration-Level Selection Policy

An integration should be able to declare:

- `default_reader_strategy`
- `fallback_reader_strategies`
- whether proxy read support exists
- whether a DI-owned native Reader exists

That allows the platform to express examples such as:

- third-party integration:
  - default `proxy`
  - no native fallback
- DI-owned optimized integration:
  - default `native`
  - fallback `proxy`
- post-remediation artifact flow:
  - default `quarantine`
  - fallback `cached`

---

## Non-Goals

This contract does not define:

- monitoring
- discovery/enumeration
- remediation
- policy
- job state

Those remain outside the Reader abstraction.

---

## Summary

The Reader contract is the stable worker-side content acquisition boundary.

It allows DSX-Connect to support:

- open, independently released integrations via ConnectorProxyReader
- higher-performance first-order integrations via native Readers
- future cached/quarantine-based read strategies

without forcing the scan worker to know repository-specific read logic.
