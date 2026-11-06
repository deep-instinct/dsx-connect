# Atlassian Jira Cloud Connector

The `jira-connector` discovers Jira spaces, enumerates issue attachments, and streams eligible files to DSX-Connect for scanning. It is a read-only adapter; comments, uploads, attachment deletion, quarantine, and webhook ingestion are not implemented. Protection settings and scan results belong to DSX-Connect.

## Prerequisites and credentials

- A running DSX-Connect 2 deployment and scanner.
- Kubernetes, Helm with OCI support, and a namespace with a suitable default StorageClass for the checkpoint PVC.
- Network access to the Jira site, `api.atlassian.com`, and the DSX-Connect API; DSX-Connect must also reach the connector service.
- A dedicated Jira account with access to the intended spaces/issues, including any issue-security restrictions.
- An Atlassian scoped API token. The classic `read:jira-work` scope is documented for [JQL search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/) and [attachment content reads](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/). If using granular scopes, consult each endpoint's current requirements, including project discovery. Token scopes do not grant project permissions.

Provision a Kubernetes Secret in `dsx-connect` through your secret-management workflow. It must contain a `token` key. For a local installation, an existing protected token file can be used:

```bash
kubectl create namespace dsx-connect --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic jira-token \
  --namespace dsx-connect \
  --from-file=token=/secure/path/jira-token
```

Do not put token values in Helm values or source control. The chart mounts the Secret and sets `DSXCONNECTOR_JIRA_API_TOKEN_FILE` for the connector.

## Deployment values

The following is a starting configuration for a non-demo deployment. Replace the site, email, stable platform key, and JQL before applying it. Save as `jira-values.yaml`:

```yaml
fullnameOverride: jira-connector
existingTokenSecret: jira-token
persistence:
  claimName: jira-monitor-data
  size: 1Gi
env:
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE: "true"
  DSXCONNECTOR_CONNECTOR_URL: "http://jira-connector:8680"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_V2_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "jira-prod-1"
  DSXCONNECTOR_PLATFORM: "jira"
  DSXCONNECTOR_PLATFORM_KEY: "example-jira-site"
  DSXCONNECTOR_DISPLAY_NAME: "Example Jira"
  DSXCONNECTOR_JIRA_SITE_URL: "https://your-site.atlassian.net"
  DSXCONNECTOR_JIRA_EMAIL: "scanner@example.com"
  DSXCONNECTOR_ASSET: "project = EXAMPLE"
  DSXCONNECTOR_JIRA_DISCOVER_SPACES: "true"
  DSXCONNECTOR_JIRA_DEMO_MODE: "false"
  DSXCONNECTOR_JIRA_DEMO_ISSUE_KEYS: '[]'
  DSXCONNECTOR_MONITOR: "false"
  DSXCONNECTOR_JIRA_POLL_INTERVAL_SECONDS: "30"
  DSXCONNECTOR_ITEM_ACTION: "nothing"
```

The service URLs above assume the same namespace. Configure TLS, trusted CAs, and deployment authentication for your environment; these settings are not credentials for Jira itself. `DSXCONNECTOR_JIRA_CLOUD_ID` can supply a cloud ID explicitly; otherwise the client resolves it from the HTTPS `*.atlassian.net` site.

The configured asset is JQL, not a bucket or filesystem path. With space discovery enabled, discovered spaces can become separate protected scopes. Review each scope's JQL: the configured asset example is not a replacement for repository permissions or a universal allowlist for all discovered spaces.

!!! warning "Chart demo defaults"
    The current chart defaults to demo mode and a test issue allowlist. Explicitly override both settings for a non-demo deployment. For a constrained trial, set `DSXCONNECTOR_JIRA_DEMO_MODE: "true"` and `DSXCONNECTOR_JIRA_DEMO_ISSUE_KEYS: '["EXAMPLE-1", "EXAMPLE-2"]'`. In demo mode, searches and direct attachment reads are restricted to that allowlist; spaces without eligible issues cannot be scanned.

## Install and verify

The repository chart is version `2.0.0`. Pin an approved published chart version:

```bash
helm upgrade --install jira \
  oci://registry-1.docker.io/dsxconnect/jira-connector-chart \
  --version 2.0.0 \
  --namespace dsx-connect \
  -f jira-values.yaml

kubectl rollout status deployment/jira-connector -n dsx-connect --timeout=120s
kubectl logs deployment/jira-connector -n dsx-connect --tail=100
```

The chart runs one replica with a persistent checkpoint volume and a Recreate strategy. For multiple installations, use distinct release names, `fullnameOverride`, checkpoint PVC names, and instance IDs. Choose the platform key deliberately: matching platform/key pairs share one integration.

Verify the deployment in stages:

1. Confirm readiness and registration under **Assets > Connectors**, including the expected platform key and version.
2. Open the connector and check space discovery. Successful registration alone does not establish Jira permissions.
3. Protect a small space/scope using a detect-only profile.
4. Use **Start Full Scan** for eligible attachments, or **Scan issues** for selected keys. Issue keys must be within the protected scope and any demo allowlist.
5. Use **View** to inspect filenames, verdicts, and item failures in Scan Results. Read-only Jira cannot carry out remediation actions.

For the confirmation, object-count limitations, submission cap, and View/Cancel behavior, see [Operating connectors and scans](../../operations/connectors-and-scans.md).

## Enable monitoring after validation

Set `DSXCONNECTOR_MONITOR: "true"` in the reviewed values and upgrade the release. Polling requires v2 registration only: core registration must remain false. Enabled protected scopes are polled at `DSXCONNECTOR_JIRA_POLL_INTERVAL_SECONDS` (default 30, minimum 10).

The first successful scope discovery establishes a baseline of existing attachment IDs. New attachment IDs then create scan-only jobs. Use a manual scan for existing attachments. Checkpoints persist across pod restarts. Failed monitoring submissions use stable idempotency keys; overlapping scopes deduplicate attachments. Those submission retries are separate from restarting an entire manual scan.

Jira search indexing can delay discovery. Monitoring does not intercept uploads or prevent attachments becoming accessible before scanning. Assess polling volume and scope breadth before enabling it across many spaces.

## Troubleshooting and removal

| Symptom | Check |
| --- | --- |
| Pod cannot mount token or data | Secret name/key, namespace, PVC binding, and StorageClass. |
| Readiness or repository check fails | Jira site/cloud ID, email, token scope/expiry, account access, outbound networking, and CA settings. |
| Connector never appears | Explicit v2 registration flags and API/advertised URLs. |
| Space discovery or reads fail | Account's project/issue access and endpoint token scopes; registration is a separate check. |
| No eligible attachments | Scope JQL, filename filters, issue selection, and demo allowlist. |
| Monitoring sees no new work | Monitoring flag, enabled scopes, baseline/checkpoints, and Jira indexing delay. |

Remove through the deployment workflow:

```bash
helm uninstall jira -n dsx-connect
```

Review checkpoint PVC/data retention before uninstalling or replacing the release. Preserve history and cancel active scans separately when required. Removing the connector does not erase DSX-Connect scan records.
