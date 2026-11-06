# Deploying Connectors

Connectors provide repository access, discovery, reads, and any supported monitoring or remediation. Deploy them through Helm or your GitOps pipeline. The Operator Console shows registered connectors and manages protected scopes, protection profiles, and scans; it does not install, stop, or upgrade connector workloads.

## Choose a connector

| Connector | Deployment guide | Notes |
| --- | --- | --- |
| Google Cloud Storage | [GCS](google-cloud-storage.md) | JSON-key and GKE workload identity examples; Pub/Sub monitoring. |
| Filesystem | [Filesystem](filesystem.md) | Mounted storage, filesystem events, and polling options. |
| AWS S3 | [AWS S3](aws-s3.md) | Credentials, S3-compatible endpoints, and event notifications. |
| Azure Blob Storage | [Azure Blob Storage](azure-blob-storage.md) | Connection-string deployment and configured-container limitations. |
| Atlassian Jira Cloud | [Jira](jira.md) | Read-only attachments, polling checkpoints, and explicit demo/production settings. |

OneDrive, M365 Mail, SharePoint, and Salesforce also have source and charts in the repository. Their [legacy connector guides](../../../connectors/index.md) are not a statement of verified DSX-Connect 2 support. Check the adapter and chart's v2 registration, discovery, read, monitoring, and remediation behavior before adopting one for a v2 deployment.

## Prepare the deployment

1. Deploy the [DSX-Connect control plane and workers](../kubernetes.md), including the scanner needed for real verdicts.
2. Choose a namespace, release name, stable platform boundary, and connector instance identity.
3. Provision repository credentials through your secret-management workflow. Required Secrets must exist in the connector's namespace. Prefer workload identity where the connector/chart supports it.
4. Grant discovery and read access for the intended repository scope. Grant write/remediation permissions only for the actions you intend to use.
5. Configure network access from the connector to the repository and DSX-Connect, and from DSX-Connect to the connector's advertised URL. Configure TLS and authentication for the target environment.
6. Review and version-control the non-secret Helm values. Pin an approved chart version; its default image tag comes from `appVersion` unless overridden.

The current repository control-plane chart is `2.0.38`. The example below pins that version; use an approved published version for your environment rather than assuming connector and control-plane versions match.

```bash
helm upgrade --install dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version 2.0.38 \
  --namespace dsx-connect \
  --create-namespace \
  -f dsx-connect-values.yaml
```

## DSX-Connect 2 registration

Every connector values file should explicitly include the v2 registration settings:

```yaml
env:
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_V2_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "connector-instance-1"
  DSXCONNECTOR_PLATFORM: "<platform>"
  DSXCONNECTOR_PLATFORM_KEY: "<operator-chosen-platform-boundary>"
```

These service URLs assume the same namespace and the standard API service name. Use a namespace-qualified service address for cross-namespace deployments. Each chart must also advertise a connector URL reachable by the control plane and scan workers; loopback addresses are not valid for communication between pods.

| Setting | Meaning |
| --- | --- |
| `DSXCONNECTOR_INSTANCE_ID` | Stable runtime instance identity. Changing it creates another instance record. Do not reuse one fixed ID across concurrent replicas. |
| `DSXCONNECTOR_PLATFORM` | Adapter type, such as `gcs`, `aws_s3`, `azure_blob_storage`, `filesystem`, or `jira`. |
| `DSXCONNECTOR_PLATFORM_KEY` | Stable, operator-chosen account/project/tenant/host boundary. Instances with the same platform and platform key share an integration. This label grants no repository access. |

Authentication and IAM determine repository access. Protected scopes determine the targets selected in DSX-Connect. Neither the platform key nor registration alone establishes protection.

## Verify in stages

| Check | What success establishes | What to investigate on failure |
| --- | --- | --- |
| Kubernetes rollout and probes | The connector process starts and reaches its readiness condition. | Image, Secret references, volume mounts, startup logs, and advertised URL. |
| Registration and heartbeats | DSX-Connect can identify the instance and receive its health reports. | Registration flags, API address, authentication, DNS, and network policy. |
| Repository check and discovery | The connector can access the configured repository and list supported assets. | Credentials, permissions, configured scope, and discovery source. |
| Small detect-only scan | Enumeration, content reads, scanner access, and result reporting work together. | Job/item failure details, reader configuration, and repository read permissions. |
| Monitoring, if configured | A subsequent eligible change creates work for an enabled protected scope. | Provider event delivery or polling/checkpoints; monitoring is a separate deployment option. |
| Remediation, if required | The intended action works on an explicitly selected test object. | Supported actions, profile configuration, and repository write permissions. |

Registration or a green liveness probe is not proof that every operation or asset is accessible. Jira is read-only; do not attempt remediation validation for it.

After deployment, follow [Operating connectors and scans](../../operations/connectors-and-scans.md). For local build scripts and helper deployments, see [Development deployment](../development.md).

## Upgrades and removal

Use the same reviewed Helm/GitOps workflow to upgrade or uninstall a connector. The console has no connector Enable/Disable control. Removing a workload stops its heartbeats; its integration and historical scan records can remain visible after the instance lease expires. Uninstalling a chart is not a scan cancellation request: cancel active scans separately when needed.
