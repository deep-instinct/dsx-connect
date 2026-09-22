# Core Concepts

DSX-Connect 2 is a control plane for protecting and governing files across repositories. It separates repository integration, protection scope, application identity, scanning, policy, remediation, and delivery.

This section describes the v2 model. For the original DSX-Connect architecture and connector API, see the [DSX-Connect v1 concepts](../concepts/architecture.md).

## The v2 model

- **Connectors** integrate repository and platform boundaries with the control plane.
- **Assets** identify repository locations and the files that can be governed.
- **Protected scopes** define which assets are monitored, scanned, or governed.
- **Applications** are callers of DSX-Connect, not repositories or assets.
- **Jobs and events** carry durable discovery, scanning, and policy state.
- **Policies and dispositions** determine what happens to a file after evaluation.

## Three protection modes

DSX-Connect 2 supports three related operating modes:

1. **Monitor repositories** to discover changes and maintain an inventory.
2. **Scan repositories** to evaluate existing content and new content against protection policy.
3. **Govern file movement** between repositories so applications can move files through a controlled interface.

The pages in this section explain the boundaries between these modes and how they fit together. The [DSX-Connect 2 overview](../dsx-connect-2/index.md) provides the broader product and architecture context.

