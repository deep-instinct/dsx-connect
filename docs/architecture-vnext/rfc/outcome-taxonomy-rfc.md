# Outcome Taxonomy RFC (Draft)

This draft defines the canonical post-scan outcome set that all scan paths must map into before policy evaluation.

## Purpose

- Decouple policy from raw DSXA/provider-specific result strings.
- Enable deterministic post-scan policy (`outcome -> action`).
- Keep remediation and notification logic consistent across connectors/platforms.

## Canonical Outcomes (Initial)

- `clean`
- `malicious`
- `unable_to_scan`
- `fetch_failed`
- `timeout`
- `unsupported_type`
- `policy_blocked`

`unable_to_scan` is a broad bucket with structured reason codes.

## Reason Codes for `unable_to_scan`

Recommended normalized reason codes:

- `encrypted_file`
- `file_too_large`
- `file_type_not_supported`
- `corrupted_file`
- `archive_nesting_limit`
- `archive_too_large`
- `zip_bomb`
- `invalid_base64`
- `invalid_hash`
- `scan_error`
- `system_initializing`

Providers may produce richer raw reasons; those should be retained in metadata while mapping to canonical reason codes.

## Normalization Contract

Finalization layer must produce:

- `raw_result`: original scanner/provider payload
- `normalized_outcome`: one canonical outcome
- `normalized_reason`: optional reason code (especially for `unable_to_scan`)
- `normalization_version`: schema version for future migrations

Example:

```json
{
  "normalized_outcome": "unable_to_scan",
  "normalized_reason": "encrypted_file",
  "normalization_version": "v1"
}
```

## Policy Evaluation Contract

Post-scan policy is evaluated on normalized fields, not raw result text.

Decision outputs:

- `remediation_action`: `none|delete|move|quarantine|tag|...`
- `notify`: boolean or channel set
- `retry`: optional retry directive

## Mapping Notes

- `malicious` should be strict and explicit.
- Transport/read failures should map to `fetch_failed`.
- Scanner runtime timeouts map to `timeout`.
- "cannot scan due to data characteristics" maps to `unable_to_scan` + reason.

## Why This Matters

- Prevents policy breakage when scanner/provider wording changes.
- Allows customers to define operational policy for non-malicious outcomes.
- Simplifies observability and reporting (`outcome` dimensions stay stable).

## Open Decisions

- Should `retryable_error` exist as a top-level outcome, or remain a policy flag derived from outcome+reason?
- Should `suspicious` be introduced later as separate outcome?
- Which reason codes are mandatory in v1 versus optional?
