# Connector and Asset Model

In DSX-Connect 2, a connector represents access to a repository platform or other governed boundary. An asset represents a location or content set within that boundary. This distinction lets one connector expose multiple repositories, paths, buckets, shares, or other scopes without turning each one into a separate platform integration.

## Connectors

A connector is responsible for platform-specific operations such as:

- discovering repositories and changes;
- reading file metadata and content;
- receiving or producing change events;
- writing, moving, or quarantining content when the platform supports it.

The connector supplies capabilities and access. The control plane supplies identity, scope, policy, job state, and audit context.

## Assets and protected scopes

An asset identifies what is being protected. A protected scope selects the assets and operations governed by a policy. The scope can cover an entire repository or a narrower location, depending on the connector and the repository platform.

This model avoids coupling policy to a particular storage implementation. The same protection concepts can apply to object storage, file shares, collaboration repositories, and application-facing gateway operations.

## Practical consequence

When configuring a deployment, first identify the platform boundary and its connector. Then define the assets and scopes that should be monitored, scanned, or available through governed file movement. Do not treat a connector credential or endpoint as a complete description of the data that is protected.

For the file gateway use case, see [Normalized Enterprise File Gateway](../dsx-connect-2/strategy/normalized-enterprise-file-gateway.md).

