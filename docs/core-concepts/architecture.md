# DSX-Connect 2 Architecture

DSX-Connect 2 is organized around a control plane and platform integrations. The control plane records what is protected, why a file was evaluated, and what disposition is required. Connectors provide access to repository platforms without making each repository the center of the policy model.

## Core boundaries

### Control plane

The control plane owns tenants, applications, protected scopes, policy decisions, job state, findings, and audit information. It provides the durable state needed to resume work, explain decisions, and apply consistent policy across different repositories.

### Connectors

Connectors adapt a repository or platform to the control plane. They handle repository-specific discovery, file access, change events, and delivery operations. A connector is a platform boundary; it is not itself the definition of the protected data set.

### Protection and scanning workers

Workers execute discovery and scanning work against the scope selected by the control plane. DSXA and other scanning services are execution components in this flow. They should not need to own repository credentials, application identity, or the complete policy model.

### Results and dispositions

Findings are associated with the asset, application, job, and policy context that produced them. A disposition can allow delivery, quarantine content, block an operation, or request remediation according to policy.

## Why the boundaries matter

This separation allows the same policy and attribution model to apply to repository monitoring, repository scans, and application-driven file movement. It also keeps connector-specific behavior isolated from the control-plane contract.

For the v2 deployment model, see [DSX-Connect 2 Deployment](../dsx-connect-2/deployment/index.md).

