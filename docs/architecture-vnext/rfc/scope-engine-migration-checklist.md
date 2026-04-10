# Scope Engine Migration Checklist

Use this checklist to migrate from connector-owned scope/filter/policy to core-owned `Integration + ProtectedScope`.

## 1. Design Freeze
- Confirm target model:
  - Connector = integration adapter only
  - Core = scope matching, filtering, policy, remediation
- Confirm constraints:
  - No-overlap scopes per integration
  - Clone defaults at scope creation (no inheritance)
- Pick pilot connector (`sharepoint` recommended).

## 2. Data Model Readiness
- Add `integrations` object (platform connection + credentials + health).
- Add `protected_scopes` object (locator + filter + policy + enabled).
- Add normalized scope locator fields:
  - ID-based: stable IDs (site/drive/item)
  - Path-based: canonical path/prefix
- Add write-time overlap validation.

## 3. Event Contract Readiness
- Define normalized event envelope from connector to core:
  - `integration_id`
  - stable resource identity (or canonical path)
  - optional ancestry/container fields
  - event type + timestamp + source cursor/sequence
- Version the contract (`event_schema_version`).

## 4. Scope Matching Engine
- Implement matcher in core:
  - ID path: exact lookup
  - Path path: canonical prefix lookup
- Guarantee match cardinality: `0 or 1` scope.
- Reject ambiguous scope definitions at write-time.

## 5. Dual-Path (Shadow) Mode
- Add feature flags:
  - `SCOPE_ENGINE_ENABLED`
  - `SCOPE_ENGINE_SHADOW_MODE`
- In shadow mode:
  - Keep legacy execution path active
  - Compute new-engine decision side-by-side
  - Emit decision diff logs/metrics only

## 6. Metrics and Observability
- Add counters:
  - `scope_match_hit_total`
  - `scope_match_miss_total`
  - `scope_overlap_reject_total`
  - `scope_shadow_diff_total`
- Add latency histograms:
  - `scope_match_latency_ms`
- Add safety counters:
  - duplicate scan suppression count
  - unscoped event drop count

## 7. Pilot Rollout
- Enable shadow mode for one integration first.
- Validate:
  - No unexpected shadow diffs
  - No duplicate scans
  - No event loss
  - Stable matcher latency
- Enable active mode for pilot integration only.

## 8. Cutover Gates
- Gate A: Shadow diff rate below threshold for agreed window.
- Gate B: No critical remediation mismatches.
- Gate C: No throughput regression on core pipeline.
- Gate D: Ops runbook updated and tested.

## 9. Rollback Plan
- Rollback switch: disable `SCOPE_ENGINE_ENABLED`.
- Preserve incoming event ingestion during rollback.
- Keep scope data; only route decisions back to legacy path.
- Alert on rollback trigger and capture root-cause artifacts.

## 10. Legacy Decommission
- Remove connector-side asset/filter/policy evaluation.
- Keep connector config compatibility as read-only shim during grace period.
- Migrate docs and UI terminology:
  - Connector -> Integration
  - Asset/Filter in connector -> Protected Scope in core

## 11. Acceptance Criteria (Done)
- All new scopes are core-managed.
- No-overlap enforcement active in production.
- Connectors no longer make policy decisions.
- Event-to-scope routing deterministic and observable.
