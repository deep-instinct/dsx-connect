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

Use the play button on a protected asset to scan its scope. To scan multiple assets, select their rows and choose **Actions → Start Scans** above the table. The confirmation shows how many scans can start and how many selections will be skipped. Full scans can use significant storage, network, and scanner resources.

The console submits up to **10,000 objects per scan request**. For larger repositories, review the job's enumeration and item outcomes to determine how much was scanned. The asset table refreshes when submission finishes.

## View results and cancel

Select rows and choose **Actions → Stop Scans** to request cancellation for their active scans. The clear-filters button beside **Actions** resets the asset name, coverage, and connector filters.

Use the blue **View** eye icon to inspect progress, findings, item failures, and remediation outcomes. Use **Clear filters** in the Scan Results toolbar to reset the preselected job and return to recent results.

The **Cancel** X icon matches the Scan Results cancellation control. It requests cooperative cancellation and shows **Cancelling…** while the request is pending. Cancellation stops future work; files already claimed by a worker may finish. A cancelled status is not proof that every in-flight repository action stopped immediately. Cancellation does not undo completed remediation.

The asset row refreshes tracked active job states every 10 seconds while the protected-assets view is visible. After completion, the blue eye opens the scan results. Failed and cancelled scans also show their status. Pause/resume is not currently supported.

## Monitoring, schedules, and recovery

Repository monitoring is configured in each connector deployment. Depending on the adapter, it consumes provider notifications, watches filesystem events, or polls the repository. It is independent of the console's table refresh.

With the scheduler enabled, open **Schedule** on a protected asset to set a daily or weekly full scan. Choose a local time and an IANA time zone, such as `America/Chicago`. The dialog shows the next run and the outcome of the most recent occurrence. Clear **Enable scheduled scans** to pause the schedule.

The scheduler submits the same full scan as the asset's play button, using the protection profile assigned when the scan runs. Scheduled jobs appear in Scan Results as **Scheduled scan**. A run is skipped if protection is disabled, a scan for that scope is already active, or its start window was missed by more than five minutes. For daylight saving changes, the scheduler runs once during a repeated hour and moves a nonexistent time forward by the size of the time change.

Enable the scheduler in Helm with `workers.scheduler.enabled=true` on a deployment that uses PostgreSQL, RabbitMQ, and the existing relay and scan workers. It runs independently of the console. Outside Helm, start `python -m dsx_connect_v2.workers.scheduler` and set `DSX_CONNECT_V2__SCAN_SCHEDULER_ENABLED=true` on the API to expose the schedule controls.

Existing job/item stages may retry according to the execution pipeline. This is separate from automatically restarting a whole full scan. Review failures and existing jobs before choosing a manual rerun. See [Failed Scans and Dead Letter Queues](../../operations/dead-letter-queues.md).
