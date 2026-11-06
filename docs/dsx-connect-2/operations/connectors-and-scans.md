# Operating Connectors and Scans

The sidebar groups **Connectors** and **Protected Assets** under **Assets**. In a collapsed sidebar, the Assets icon opens a flyout with these views. Page headings (**Assets > Connectors** or **Assets > Protected Assets**) and the selected sidebar item identify the view; there is no top breadcrumb or duplicate asset tab bar.

Connector installation, credentials, monitoring configuration, upgrades, and removal belong to the deployment workflow. Use the Operator Console to inspect registered connectors, select protected scopes, assign protection profiles, and operate scan jobs. See [Deploying connectors](../deployment/connectors/index.md) for setup and verification.

## Inspect a connector

Open **Assets > Connectors**. The table reports connector health, registered instances and versions, protected scope counts, capabilities, and endpoints. Click a connector row to open its assets.

The connector table refreshes automatically every 30 seconds while visible, and immediately on entering the view or returning to the browser tab. It pauses while hidden. Use Refresh for an immediate check. This refresh updates registration and health summaries; it does not enable repository monitoring or scan newly discovered content.

Health and registration do not prove that every listed repository is readable. Check discovery and run a small detect-only scan before relying on a deployment. Repository access and monitoring remain deployment concerns; there is no connector Enable/Disable control.

## Filter connectors

The **Connector** column filter supports **All connectors** or a selected subset. Open it to search by name, platform, or account/project label. Use **Select search results** to select exactly the visible matches, **Show selected only** to review a long selection, and **Clear selection** to start over. The selected/shown counts distinguish the checked set from the search results. Search does not itself change the applied filter.

Choose **Apply filters** to update the asset table once, or dismiss/Cancel to retain the current filter. At least one connector must be checked; selecting all connectors represents the All filter. Individual connector rows still open assets filtered to that connector.

Pagination carries independent positions for each connector and bounds the combined page size. Bulk **Select all matching assets** uses the complete selected connector set and current asset filters. It rejects incomplete discovery rather than applying changes to a silently partial inventory.

## Discover and protect assets

1. Open the connector's asset view, or **Assets > Protected Assets**, and select the intended connector.
2. Use the **All** or **Unprotected** coverage filter to find supported discovered assets. Discovery sources and available asset types vary by connector.
3. Use the **Protection Profile** dropdown to assign or change a profile for the intended asset/scope. It shows **Unprotected** when protection is not enabled, or the applied profile name when it is. Selecting a profile opens a confirmation showing the asset and current/new profile. Applying it enables protection. Changing, resuming, or disabling protection also requires confirmation; Cancel or Escape leaves the current setting unchanged. Start with detect-only behavior when validating a deployment.
4. Confirm the selected scope, effective protected entity, and protection profile before scanning.

A green check beside the asset name means protection is configured. An amber minus means unprotected or disabled; the tooltip distinguishes these states. Unknown protection uses a neutral question mark. These indicators describe protection configuration, not scan verdicts. A disabled scope shows **Unprotected**, retains its previous profile in the tooltip, and offers a Resume option. Selecting **Unprotected — disable protection** disables the scope without deleting its saved profile. The coverage filter remains in the Protection Profile column.

Discovery makes content locations visible. It does not automatically protect them or enable monitoring. The effective protection profile can include remediation, so a scan may cause repository changes when supported and configured.

## Start a full scan

Select protected assets in the table, then choose **Start Scan**. Review shows how many eligible scans can start and how many selections will be skipped. Full scans can use significant storage, network, and scanner resources.

The console submits up to **10,000 objects per scan request**. For larger repositories, review the job's enumeration and item outcomes to determine how much was scanned. After confirming, the operation panel shows scan submission progress, and the asset table refreshes when submission finishes.

## View results and cancel

Use the blue **View** eye icon to inspect progress, findings, item failures, and remediation outcomes. The toolbar shows a compact **Selected scan** or **Time range** chip when a server-side filter is active. Use its **Clear scan filter** X to return to recent results. There is no automatic-navigation return button or repeated job-summary paragraph.

The **Cancel** X icon matches the Scan Results cancellation control. It requests cooperative cancellation and shows **Cancelling…** while the request is pending. Cancellation stops future work; files already claimed by a worker may finish. A cancelled status is not proof that every in-flight repository action stopped immediately. Cancellation does not undo completed remediation.

The asset row refreshes tracked active job states every 10 seconds while the protected-assets view is visible. After completion, the blue eye opens the scan results. Failed and cancelled scans also show their status. Pause/resume is not currently supported.

## Monitoring, schedules, and recovery

Repository monitoring is configured in each connector deployment. Depending on the adapter, it consumes provider notifications, watches filesystem events, or polls the repository. It is independent of the console's table refresh.

Scheduled scans are not currently implemented. Scan submission starts work now; the console has no future-time or recurring-schedule control. There is no scheduler catch-up feature that starts missed scans after recovery.

Existing job/item stages may retry according to the execution pipeline. This is separate from automatically restarting a whole full scan. Review failures and existing jobs before choosing a manual rerun. See [Failed Scans and Dead Letter Queues](../../operations/dead-letter-queues.md).
