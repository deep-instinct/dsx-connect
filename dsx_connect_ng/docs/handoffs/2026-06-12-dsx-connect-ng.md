# DSX-Connect NG Handoff - 2026-06-12

This document is a resume-state handoff for a new Codex session with no prior memory.

## Project Overview

`dsx_connect_ng` is the standalone next-generation DSX-Connect application boundary. It is intentionally separate from legacy `dsx_connect` and owns the new control-plane-first architecture, job orchestration model, worker contracts, result sink pipeline, local runtime, and operator UI routes.

The key architectural direction is:

- control-plane APIs manage integrations, protected scopes, policies, and protection intent
- execution APIs manage jobs, job items, stage transitions, worker/backend contracts, and reliable scan-path state
- UI APIs provide browser/operator-console aggregation and convenience workflows only
- connectors are integration adapters and capability providers, not policy engines
- PostgreSQL and RabbitMQ are the intended durable infrastructure, with memory backends used for tests and local preview

## Current Branch

Current branch:

```text
main
```

At the time this handoff was written, the NG work is local/uncommitted. There is also unrelated dirty work in other parts of the repo, especially `dsx_transfer/`. Do not revert or clean unrelated files.

## Files Changed

### DSX-Connect NG

Modified:

```text
dsx_connect_ng/README.md
dsx_connect_ng/dsx_connect_ng/api/routes/ui.py
dsx_connect_ng/dsx_connect_ng/ui/operator_console.html
dsx_connect_ng/tests/test_ui_routes.py
```

Untracked/new docs directory:

```text
dsx_connect_ng/docs/
dsx_connect_ng/docs/index.md
dsx_connect_ng/docs/architecture.md
dsx_connect_ng/docs/api-boundaries.md
dsx_connect_ng/docs/runtime.md
dsx_connect_ng/docs/handoffs/2026-06-12-dsx-connect-ng.md
```

### Adjacent Non-NG Dirty Work

There is active DSX-Transfer work in the same worktree. It is not part of this NG handoff and should not be changed unless explicitly requested:

```text
docs/dsx-transfer/index.md
dsx_transfer/
```

## Why Each NG Change Was Made

### `dsx_connect_ng/dsx_connect_ng/ui/operator_console.html`

Rebuilt the operator console from the earlier hero/form/card-style UI into a denser operational console.

Current UI shape:

- top-level tabs: `Assets`, `Scan Results`, `Policy`
- `Assets` has subtabs for `Connectors` and `Protected`
- right rail contains operator workflows:
  - create/update integrations
  - protect assets/scopes
  - run scans
  - assign/update policy
- UI is designed for operational scanning, comparison, and repeated actions rather than marketing/landing-page presentation

Important small fix already made:

- added explicit `protectedAssetsLoaded` state so the Protected assets tab does not repeatedly reload when the protected asset result set is legitimately empty

### `dsx_connect_ng/dsx_connect_ng/api/routes/ui.py`

Added UI-specific aggregation and workflow endpoints that serve the operator console without polluting machine-facing control-plane or execution contracts.

Important additions:

- UI integration create/update/toggle flow
- connector asset listing:
  - `/api/v1/ui/assets/connectors`
- protected asset aggregation:
  - `/api/v1/ui/assets/protected`
- policy list/update flow:
  - `/api/v1/ui/policies`
  - `/api/v1/ui/scopes/{scope_id}/policy`
- scan result summary endpoint:
  - `/api/v1/ui/scan-results`
- scope scan remains wired through:
  - `/api/v1/ui/scopes/{scope_id}/scan`

The UI route layer now composes backend records into human-facing summaries for:

- connectors
- protected assets
- policies
- scan results
- findings
- remediation state
- cooperative cancel semantics

### `dsx_connect_ng/tests/test_ui_routes.py`

Expanded targeted API coverage for the operator UI route layer.

Coverage includes:

- operator console page render
- integration summary including scope counts and health
- connector listing for the Assets > Connectors tab
- protected asset aggregation
- scan-result summaries
- state filtering
- policy assignment/update
- scope scan submission
- operator workflow smoke test

### `dsx_connect_ng/README.md`

Updated the package-level README to point to package-local docs under `dsx_connect_ng/docs/` and reinforce the current API family boundaries, runtime commands, worker model, reader strategy model, and local preview guidance.

### `dsx_connect_ng/docs/*`

Started package-local documentation so NG has its own docs area instead of relying only on the root README.

Current docs:

- `index.md`: start page and principles
- `architecture.md`: application boundary, worker model, reader boundary, connector capability model
- `api-boundaries.md`: control-plane vs execution vs UI API separation
- `runtime.md`: install/run/local preview/runtime manager notes
- `handoffs/2026-06-12-dsx-connect-ng.md`: this resume-state document

## Design Decisions That Must Not Be Reversed

1. `dsx_connect_ng` must remain isolated from legacy `dsx_connect`.

   Do not add imports from `dsx_connect.*` into NG. NG may use neutral/shared packages such as `shared` where appropriate.

2. Keep API families separate.

   - control-plane: machine contract for integration/protection metadata
   - execution: machine contract for jobs, worker state, and scan-path reliability
   - UI: frontend/operator aggregation only

   Do not move worker/backend contracts into UI routes just because it is convenient for the page.

3. UI routes may aggregate, but must not become connector contracts.

   `/api/v1/ui/...` exists for the browser/operator console. Connectors, workers, and automation should use control-plane or execution APIs.

4. PostgreSQL and RabbitMQ remain first-class durable targets.

   Memory backends are for tests and local UI preview. They are not substitutes for validating durable multi-process behavior.

5. The operator console should remain operational and dense.

   Avoid reverting to a marketing-style hero page, oversized cards, or explanatory in-app copy. The first screen should be the usable console.

6. Connector direction is capability-based.

   Connectors should be thought of as components/capabilities such as Discoverer, Reader, Remediator, EventSource, IdentityResolver, CredentialProvider, and CapabilityManifest. DSX-Connect NG orchestrates workflows; connectors expose platform capabilities.

7. Cancel semantics are cooperative.

   The UI/API should communicate that cancel stops future work quickly, but already claimed in-memory scan batches may finish.

## Test Status

Focused NG UI route suite:

```bash
./.venv/bin/python -m pytest dsx_connect_ng/tests/test_ui_routes.py
```

Last local result:

```text
12 passed
```

Local preview smoke checks previously passed for:

```text
/api/v1/ui/status
/api/v1/ui/
/api/v1/ui/assets/connectors
/api/v1/ui/scan-results
```

Important local preview caveat:

Running the app without memory backend settings may try to connect to local PostgreSQL on `127.0.0.1:5432`. For UI-only preview, use memory backends unless intentionally bringing up local NG PostgreSQL/RabbitMQ.

Recommended UI preview command:

```bash
DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=memory \
DSX_CONNECT_NG__JOB_BUS_BACKEND=memory \
./.venv/bin/python -m uvicorn dsx_connect_ng.app:app --host 127.0.0.1 --port 8093
```

Preview URL:

```text
http://127.0.0.1:8093/api/v1/ui/
```

## Outstanding TODOs

- Run broader NG tests beyond the targeted UI route suite.
- Verify the operator console visually in browser after any CSS/layout edits.
- Check mobile/narrow viewport behavior for the dense console and right rail.
- Decide whether the new package-local docs should be added to root `mkdocs.yml` or linked only from `dsx_connect_ng/README.md`.
- Improve seeded/demo data for local operator UI preview so the console is easier to show without manual setup.
- Continue hardening policy editing UX and validation feedback.
- Confirm protected asset aggregation behavior against durable PostgreSQL state, not only memory tests.
- Confirm scan result summary behavior against realistic multi-item batch jobs and failed/cancelled/remediation states.
- Keep DSX-Transfer work separate unless explicitly asked to bridge the two efforts.

## Suggested Next 3 Tasks

1. Start the memory-backend UI preview and inspect the operator console in a browser.

   Use port `8093` if `8091` is occupied:

   ```bash
   DSX_CONNECT_NG__CONTROL_PLANE_BACKEND=memory \
   DSX_CONNECT_NG__JOB_BUS_BACKEND=memory \
   ./.venv/bin/python -m uvicorn dsx_connect_ng.app:app --host 127.0.0.1 --port 8093
   ```

2. Run a broader NG test pass and fix any regressions caused by the UI/API route additions.

   Start with:

   ```bash
   ./.venv/bin/python -m pytest dsx_connect_ng/tests
   ```

3. Convert the current operator console state into a committed slice.

   Suggested commit contents:

   - `dsx_connect_ng/dsx_connect_ng/ui/operator_console.html`
   - `dsx_connect_ng/dsx_connect_ng/api/routes/ui.py`
   - `dsx_connect_ng/tests/test_ui_routes.py`
   - `dsx_connect_ng/README.md`
   - `dsx_connect_ng/docs/`

   Before committing, review the dirty worktree carefully and do not include unrelated DSX-Transfer or connector changes unless explicitly intended.
