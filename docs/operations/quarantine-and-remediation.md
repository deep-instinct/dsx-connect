# Quarantine and Remediation Operations

This guide explains how DSX-Connect NG handles quarantine naming and repository-side remediation.

It is operator-focused.

For architectural background, see the vnext design notes on remediation and quarantine targets.

## Core Principle

In 2g, the core is authoritative for:

* what remediation action should happen
* where quarantined content should go
* what the quarantined object should be named

Connectors should normally execute that request using repository-native APIs.

This keeps policy, naming, and quarantine conventions centralized instead of reimplemented per connector.

## Default Quarantine Behavior

The default quarantine model is:

* move to the configured quarantine area
* append a stable suffix to the quarantined filename
* do not preserve the original relative source path under quarantine

Example:

* source object: `ng-e2e/scan/eicar.txt`
* quarantine target: `ng-e2e/quarantine`
* quarantined object: `ng-e2e/quarantine/eicar.txt_9099f2a754`

This means quarantine behaves like a dump area, not a mirrored source tree.

That is intentional because:

* the original location is already recorded in workflow state
* mirrored paths make quarantine areas noisy and harder to inspect
* operators usually care more about quick access to quarantined artifacts than preserving source hierarchy

## Filename Suffixing

Quarantined filenames are expected to be suffixed by core.

Recommended shape:

* `<original_filename>_<suffix>`

Examples:

* `invoice.pdf_item4`
* `bad.exe_c23bbf85bc`

Benefits:

* avoids overwrite
* makes quarantined artifacts visibly distinct
* neutralizes the original terminal extension
* keeps naming deterministic and traceable

Where possible, the suffix should be derived from workflow identity such as `job_item_id`.

## Policy Setting

The quarantine target supports:

* `path` or `prefix`
* `preserve_relative_path`
* `collision_strategy`
* `suffix_length`

Current default:

* `preserve_relative_path = false`
* `collision_strategy = suffix_random`
* `suffix_length = 10`

Operationally, `preserve_relative_path = false` means files land directly in the quarantine area unless a policy explicitly opts into path preservation.

## Connector Expectations

For repository-style connectors, the preferred contract is:

1. core resolves the destination path or prefix
2. core resolves the quarantined filename
3. connector executes the move/tag/delete request

Connectors may still need to do platform-specific translation, for example:

* object key assembly for S3, GCS, and Azure Blob
* move-to-folder plus rename for SharePoint or OneDrive
* capability-based degradation when the platform cannot support a requested action

But connectors should not normally invent quarantine naming policy on their own.

## Operational Recommendations

Use a dedicated quarantine area when possible.

Examples:

* filesystem: dedicated quarantine directory
* object storage: dedicated quarantine prefix
* collaboration platforms: dedicated quarantine folder

Also consider:

* lifecycle or retention rules for quarantine storage
* restricted access controls on quarantine destinations
* downstream review or release workflows
* audit visibility into original location, verdict, and remediation outcome

## Current Connector Direction

The current direction for supported file-style connectors is:

* Filesystem: honors core-provided destination and filename
* GCS: honors core-provided destination and filename
* S3: honors core-provided destination and filename
* Azure Blob: honors core-provided destination and filename
* SharePoint: honors core-provided destination folder and filename
* OneDrive: honors core-provided destination folder and filename

Some connectors may still have capability limits around tagging or repository-native move semantics.

When that happens, the connector should return a clear degraded or unsupported outcome rather than silently changing policy behavior.
