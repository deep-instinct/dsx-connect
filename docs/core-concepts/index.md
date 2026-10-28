# Core Concepts

DSX-Connect 2 is a control plane for protecting and governing files across repositories. It separates repository integration, protection scope, application identity, scanning, policy, remediation, and delivery.

This section describes the v2 model. For the original DSX-Connect architecture and connector API, see the [DSX-Connect v1 concepts](../concepts/architecture.md).

## The v2 model

- **Connectors** integrate repository and platform boundaries with the control plane.
- **Assets** identify repository locations and the files that can be governed.
- **Protected scopes** define which assets are monitored, scanned, or governed.
- **Applications** are virtual entities defined in DSX-Connect that map real callers to permitted actions, destinations, and attribution, so their file activity can be managed and tracked.
- **Jobs and events** carry durable discovery, scanning, and policy state.
- **Policies and dispositions** determine what happens to a file after evaluation.

## Three protection modes

DSX-Connect 2 supports three related operating modes:

1. **[Repository monitoring](repository-monitoring.md)** evaluates content as changes are detected.
2. **[Full repository scans](repository-full-scan.md)** enumerate and evaluate existing content in a protected scope.
3. **[Governed file movement](governed-file-movement.md)** applies scanning, policy, and delivery controls to application uploads and transfers.

The **DSX-Connect File Workflows** section contains the three pages above, with diagrams highlighting each path through the architecture. Start with [DSX-Connect 2 Architecture](architecture.md), [Connector and Asset Model](connectors-and-assets.md), and [Application Identity and Attribution](../dsx-connect-2/concepts/application-identity-and-attribution.md) to understand the concepts those workflows use. The [DSX-Connect 2 overview](../dsx-connect-2/index.md) provides the broader product context.

