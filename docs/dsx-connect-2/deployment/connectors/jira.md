# Atlassian Jira Cloud connector

The `atlassian-jira-connector` discovers Jira spaces, enumerates issue attachments,
and streams eligible files into DSX Connect for scanning. Jira access is read-only.
Protect settings, scan jobs, and results are stored in DSX Connect.

## Authentication

Create an Atlassian scoped API token with classic `read:jira-work`. This covers project
metadata, issue discovery, and attachment downloads. The account still needs access to
the selected spaces and issues. No Jira administrator or write scopes are required.

Store the token in a Kubernetes Secret with a `token` key. Reference the Secret using
`existingTokenSecret` in the connector Helm values. Never put the token in source control.

## Deployment

```bash
helm upgrade --install jira \
  oci://registry-1.docker.io/dsxconnect/jira-connector-chart \
  --version 2.0.0 --namespace dsx-connect \
  -f jira-values.yaml
```

Example values for a constrained demonstration:

```yaml
existingTokenSecret: jira-token
env:
  DSXCONNECTOR_JIRA_SITE_URL: https://your-site.atlassian.net
  DSXCONNECTOR_JIRA_EMAIL: you@example.com
  DSXCONNECTOR_JIRA_DISCOVER_SPACES: "true"
  DSXCONNECTOR_JIRA_DEMO_MODE: "true"
  DSXCONNECTOR_JIRA_DEMO_ISSUE_KEYS: '["DEMO-1", "DEMO-2"]'
  DSXCONNECTOR_ASSET: ""
  DSXCONNECTOR_MONITOR: "true"
  DSXCONNECTOR_JIRA_POLL_INTERVAL_SECONDS: "30"
```

The connector uses the shared framework for DSX Connect 2 registration. Configure its
advertised URL, DSX Connect address, and enrollment/authentication settings for the target
network. The chart runs one replica with a persistent volume for polling checkpoints.

## Protect and scan

1. Open **Protect** and select the Jira connector.
2. Choose a space and apply a detect-only protection profile.
3. Use **Full Scan** for all eligible attachments, or **Scan issues** for selected issue keys.
4. Review the original filenames and verdicts in **Scan Results**.

Space discovery reads only project metadata. In demo mode, all searches and direct
attachment reads are restricted to the deployment's issue allowlist. Spaces without
approved issues are labeled **Demo scans disabled**. Selecting a space does not expand
the allowlist or change Jira permissions.

## Monitoring

Monitoring is a deployment option (`DSXCONNECTOR_MONITOR=true`). Enabled protected scopes
are polled every 30 seconds by default. The first successful discovery establishes a
baseline; newly discovered attachment IDs then create scan-only jobs. Full Scan remains
available to scan existing attachments.

Checkpoints persist across pod restarts. Failed submissions retry with stable idempotency
keys, and overlapping scopes do not submit the same attachment twice. Jira search indexing
may delay discovery beyond one poll interval.

The connector does not intercept uploads or block files before they become available in
Jira. It does not create comments, edit issues, upload files, delete attachments, or create
spaces. Broad production deployments should assess polling volume and use narrower JQL
scopes as appropriate.
