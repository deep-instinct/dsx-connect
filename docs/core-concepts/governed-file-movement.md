# Governed File Movement

Governed file movement is the application-facing use of DSX-Connect 2. An application submits a file operation to the gateway instead of moving content directly between repositories. The gateway applies identity, access control, scanning, and policy before allowing the operation to complete.

## The request path

1. An application authenticates to the gateway and requests a file operation.
2. The gateway identifies the application and the source and destination assets.
3. The control plane evaluates access and protection policy.
4. The content is scanned or the existing evaluation is checked.
5. The gateway allows, blocks, quarantines, or remediates the operation.
6. The result is recorded with application, asset, job, and policy context.

The exact execution path can vary by repository platform, but the governance boundary remains the same: applications use the gateway contract, while repository-specific access stays behind connectors.

## Repository access versus gateway access

Repository access answers whether a principal can access a location directly. Gateway access answers whether an application is allowed to perform a particular governed operation. These are separate controls and should not be collapsed into a single repository credential.

This model is described in more detail in [Gateway Access Control](../dsx-connect-2/strategy/gateway-access-control.md), [Application Identity and Attribution](../dsx-connect-2/concepts/application-identity-and-attribution.md), and [Developer File API versus MFT](../dsx-connect-2/strategy/developer-file-api-vs-mft.md).

