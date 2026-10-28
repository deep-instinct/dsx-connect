# Full Repository Scan

A full scan evaluates existing content within a selected protected scope. An operator or application requests the scan, and the connector enumerates matching files. Each file enters the durable scan and policy pipeline.

![Full repository scan flow](../assets/diagrams/dsx-connect-2-flow-full-scan.svg#only-light)
![Full repository scan flow](../assets/diagrams/dsx-connect-2-flow-full-scan-dark.svg#only-dark)

## Flow

1. An operator or application requests a scan of a configured repository scope.
2. The connector enumerates content within that scope and applies the configured filters.
3. The control plane records the job, file items, and pending outbox events in PostgreSQL.
4. The relay dispatches work through RabbitMQ. Scan workers read file content through the configured reader strategy and request DSXA verdicts.
5. Policy workers evaluate each verdict. Remediation and optional DIANNA stages run when required; result-sink workers publish outcomes.
6. Stage transitions and item outcomes are persisted for job progress, reporting, and recovery.

## Scope and completion

A full scan covers the selected scope and filters, subject to repository access and enumeration success. Review item failures and pending stages before treating a job as complete. Repository content may change during enumeration or scanning, so a completed scan is not an immutable snapshot of the repository.

Run a full scan when onboarding a repository, establishing a baseline, or reevaluating existing files. Pair it with [repository monitoring](repository-monitoring.md) to evaluate subsequent changes. See [Failed Scans and Dead Letter Queues](../operations/dead-letter-queues.md) for failed work and [Quarantine and Remediation](../operations/quarantine-and-remediation.md) for dispositions.
