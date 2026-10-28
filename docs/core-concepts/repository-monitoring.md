# Repository Monitoring

Monitoring protects a configured repository scope as content changes. The connector observes repository events or detects changes through scheduled discovery, then submits the affected files for evaluation. It complements a full scan by keeping protection current between baseline scans.

![Repository monitoring flow](../assets/diagrams/dsx-connect-2-flow-monitoring.svg#only-light)
![Repository monitoring flow](../assets/diagrams/dsx-connect-2-flow-monitoring-dark.svg#only-dark)

## Flow

1. A file is created or changed within a protected scope.
2. The connector detects the change and reports it to the control plane with repository and asset context.
3. The API records accepted work and pending outbox events in PostgreSQL.
4. The relay publishes work to RabbitMQ. Scan workers obtain content through the connector and request a DSXA verdict.
5. Policy determines the disposition. Remediation workers perform any required repository action; result-sink workers deliver the outcome.
6. Workers persist stage state and results so operators can inspect the job and recover failed work.

## Coverage and operations

Monitoring depends on the connector's event and discovery capabilities and its repository permissions. Configure the protected scope and filters to match the content that needs evaluation. Scheduled discovery can detect changes missed by event delivery; monitoring alone should not be treated as proof that all existing content has been scanned.

Use a [full repository scan](repository-full-scan.md) to establish a baseline or reevaluate an existing scope. Inspect findings and actions through the Operator Console and [Quarantine and Remediation](../operations/quarantine-and-remediation.md).
