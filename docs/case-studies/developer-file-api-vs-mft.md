# Developer File API and Managed File Transfer

## Scenario: Partner Uploads into an Enterprise Repository

A third-party claims application needs to submit documents to an enterprise's approved storage location. The enterprise wants Security to own file-handling decisions and IT / DevOps to own repository access.

The team defines a DSX-Connect Application for the partner, grants it a destination and path, and supplies gateway credentials. The partner discovers its allowed destinations and uploads through the gateway. Connector credentials provide repository access inside the enterprise.

## Division of Responsibilities

| Responsibility | DSX-Connect File Gateway | Managed file transfer platform |
| --- | --- | --- |
| Application integration | Destination discovery and file submission API | Product-specific transfer interfaces |
| Security workflow | DSXA scanning, policy, and supported remediation or delivery stages | Depends on the product and security integrations |
| Repository access | Connector deployments managed by IT / DevOps | Endpoint and protocol configuration |
| Partner transport | Gateway API access through Application grants | Partner onboarding and supported transfer protocols |
| Scheduled or bulk movement | Evaluate the implemented workflow for the intended use | Common focus of MFT products |
| Operational visibility | File-job, scan, policy, and delivery outcomes | Transfer status and transport audit |

MFT capabilities vary by product. Select a platform based on its actual protocols, retry behavior, scale, and integrations.

## Gateway Upload Walkthrough

1. IT / DevOps deploys a connector with bounded repository permissions.
2. Security configures the protected destination and file-handling policy.
3. An operator creates an Application for the partner with destination, action, and path grants.
4. The partner calls `GET /api/v1/files/destinations` and chooses an allowed destination.
5. It submits files using `POST /api/v1/files/transfers`.
6. DSX-Connect records the job, scans the files, applies policy, and runs configured downstream stages.
7. The partner inspects the outcome. Acceptance into processing and successful delivery are distinct states.

![Gateway upload workflow](../assets/diagrams/dsx-connect-2-flow-gateway-upload.svg#only-light)
![Gateway upload workflow](../assets/diagrams/dsx-connect-2-flow-gateway-upload-dark.svg#only-dark)

Available handling actions depend on policy configuration and connector capabilities. Repository-to-repository gateway transfers remain a planned path.

## Working Alongside MFT

An existing MFT platform can deliver files to a landing zone monitored by a DSX-Connect connector. In that arrangement, MFT owns transport and DSX-Connect evaluates repository content after arrival. Downstream consumers need an explicit release or processing boundary if files must be evaluated before use.

Applications can also use the gateway directly for uploads requiring enterprise-controlled processing before destination delivery. Integrating DSX-Connect ahead of an MFT route requires an explicit integration; it is not an automatic property of deploying either system.

## Why the Gateway Boundary Matters

A scanning service returns a verdict and leaves each application team to implement file handling. The governed gateway places those decisions with enterprise Security and keeps repository credentials with IT / DevOps. External developers implement submission and outcome handling through their Application grants.

See [Application Identity and Attribution](../dsx-connect-2/concepts/application-identity-and-attribution.md) and [Governed File Movement](../core-concepts/governed-file-movement.md) for the operating model.
