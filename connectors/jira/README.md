# Jira Cloud attachment connector (prototype)

Read-only Jira Cloud connector using the shared DSX connector framework. It discovers
issue attachments through enhanced JQL search and streams their bytes when DSX Connect
requests a file. DSX Connect owns scan execution and results; this service does not
call DSXA directly.

## Supported

- Explicit JQL scope (`DSXCONNECTOR_ASSET`), e.g. `key = TEST-123` or `project = TEST`.
- Full-scan enqueueing, preview, repository check, configured-scope discovery, and
  paginated object listing for DSX Connect 2.
- Stable identity: Jira cloud ID + attachment ID. Scan location is the numeric attachment ID.
- Filename filters using the shared connector filter syntax.
- Scoped API tokens supplied as a secret or a mounted token file.
- Streaming downloads with redirect suppression, bounded transient retries, and TLS verification.

Polling with persistent checkpoints is supported for DSX Connect 2. Webhook ingestion,
comments, uploads, attachment deletion, and quarantine are not implemented. Repeated full
scans intentionally submit attachments again. Jira attachments become available before
scanning; this connector does not intercept uploads. It advertises remediation and
write capabilities as false and rejects non-`nothing` item-action configuration.

## Jira setup

The account needs Browse Projects and access to any issue security restrictions.
Create a scoped API token with these read scopes for GET enhanced search and content:

- `read:issue-details:jira`
- `read:audit-log:jira`
- `read:avatar:jira`
- `read:field-configuration:jira`
- `read:issue-meta:jira`
- `read:attachment:jira`

[Search API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/)
[Attachment API](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/)

Use a dedicated test issue/project first. The connector cannot expand the account's
permissions. Token scopes do not restrict access to a particular project; the JQL scope
controls discovery. Authenticated read_file requests can retrieve any numeric attachment
ID accessible to the account on the configured site, as with a repository credential.

## Local run

From the repository root, install `connectors/jira/requirements.txt` into your environment.
Set the following in your terminal (substitute your site, email, and test issue):

```bash
export DSXCONNECTOR_JIRA_SITE_URL=https://your-site.atlassian.net
export DSXCONNECTOR_JIRA_EMAIL=you@example.com
export DSXCONNECTOR_JIRA_API_TOKEN_FILE="$HOME/jira"
export DSXCONNECTOR_ASSET='key = TEST-123'
export DSXCONNECTOR_CONNECTOR_URL=http://localhost:8680
export DSXCONNECTOR_DSX_CONNECT_URL=http://localhost:8586
python -m connectors.jira.start
```

The token file contains only the token. Alternatively set `DSXCONNECTOR_JIRA_API_TOKEN`.
No token is committed or copied into the image. `JIRA_CLOUD_ID` (with the same
`DSXCONNECTOR_` prefix) may be supplied to skip site ID discovery. Only scoped-token
routing through `api.atlassian.com/ex/jira/{cloudId}` is implemented.

For DSX Connect 2, set `DSXCONNECTOR_REGISTER_WITH_CORE=false`,
`DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE=true`, and
`DSXCONNECTOR_DSX_CONNECT_V2_URL` to your control plane. Configure enrollment/HMAC
using the shared framework's deployment settings. Set the advertised connector URL
so the core/control plane can reach it; localhost is suitable only on the same host.

## Docker

Copy `deploy/docker/.env.example` to `deploy/docker/.env` and fill in values, including
an absolute `JIRA_TOKEN_FILE`. Then run from that directory:

```bash
docker compose up --build
```

Ensure the non-root container user can read the mounted secret file. Adjust the
advertised connector URL and DSX Connect address for your network.

Object listing returns at most the requested attachment limit, with an opaque cursor
that carries the upstream Jira page token and attachment offset. Cursors are tied to
JQL scope. Concurrent Jira changes can affect a traversal; this is not snapshot isolation.

## Validation

```bash
python -m pytest connectors/jira/tests -q
```

Live validation on RD-28133 discovered six attachments and streamed the smallest
attachment (22,071 bytes). On October 28, 2026, the connector was deployed to k3s-uslab,
registered as healthy, and completed a DSX Connect job for all six attachments:
**6 Benign, 0 failures**. Jira was not modified.

## Current lab deployment

- Namespace/deployment/service: `dsx-connect` / `jira-connector` / `jira-connector`
- Integration: `int_4552c881023147e78d88282c3cf5fdc8`
- Scope: `scope_6710b3a210184c00aeaa1beb8de4c848` (`key = RD-28133`)
- Verified job: `job_5083b878615d4cd9a2a83afce4d46908`
- Token is in Kubernetes Secret `jira-prototype-token`; no token is stored in source.

`deploy/kubernetes/lab.yaml` now uses the standalone `dsxconnect/jira-connector:2.0.0`
image. The old source ConfigMap deployment is retired. The legacy bundle helper remains
available for development; released deployments do not need it.

To reproduce the lab deployment from the repository root:

```bash
kubectl --context k3s-uslab -n dsx-connect create secret generic jira-prototype-token \
  --from-file=token="$HOME/jira" --dry-run=client -o yaml | \
  kubectl --context k3s-uslab apply -f -
kubectl --context k3s-uslab apply -f connectors/jira/deploy/kubernetes/lab.yaml
```

After updating the token, restart only `deployment/jira-connector`. Build a new versioned image for code changes.
The lab manifest exposes a cluster-internal service only and follows the existing lab's
unauthenticated connector API configuration. Configure connector authentication before
using this deployment pattern outside the lab.

## Demo Spaces mode

The lab now runs with:

```bash
DSXCONNECTOR_JIRA_DEMO_MODE=true
DSXCONNECTOR_JIRA_DEMO_ISSUE_KEYS='["RD-28133"]'
DSXCONNECTOR_ASSET=
```

Protect shows **R&D (RD) — Selected issues: RD-28133**. Its selector is the real
space-level JQL `project = "RD"`. Every search is intersected with the issue allowlist,
so Full Scan on that space scans only attachments on RD-28133. Direct attachment
reads are checked against the allowlist too. Empty allowlists are rejected in demo mode.

Space names come from project metadata on approved issues, using the existing token
scopes. This deliberately shows only spaces represented by approved demo issues;
it does not enumerate all production spaces or their issues. The space row initially
appears unprotected so you can demonstrate Protect and then Full Scan. The previous
single-issue protected scope and its scan history remain stored.

To add another demo issue, update `DSXCONNECTOR_JIRA_DEMO_ISSUE_KEYS` in
`deploy/kubernetes/lab.yaml` and apply it. Keep `DSXCONNECTOR_ASSET` empty, or use it as
an additional restriction. For multiple spaces, add an approved issue from each space.
The display label lists exactly the selected issues for each space.


## Automatic attachment polling

The lab checks enabled protected scopes every **30 seconds**. It obeys the demo issue
allowlist and filename filters. Disabled integrations/scopes are skipped. When spaces
and individual issues overlap, the space-level scope is preferred and each attachment
is submitted once per integration.

The first successful discovery establishes a baseline without submitting historical
attachments. New attachment IDs then create scan-only jobs with original filenames
and issue-key attribution. To scan existing attachments, use Full Scan. An attachment
that becomes eligible through a newly added protected scope after baseline initialization
can also be submitted on the next poll.

Configuration:

```bash
DSXCONNECTOR_MONITOR=true
DSXCONNECTOR_JIRA_POLL_INTERVAL_SECONDS=30
DSXCONNECTOR_JIRA_CHECKPOINT_FILE=/app/data/jira-monitor.sqlite3
DSXCONNECTOR_REGISTER_WITH_CORE=false
DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE=true
```

SQLite checkpoints live on PVC `jira-monitor-data` in the lab. Successful submissions
are checkpointed after API acceptance; retry attempts use a deterministic idempotency
key to avoid duplicate jobs after timeouts or restarts. A failed page does not commit a
partial initial baseline. This tracks job submission, not final scan completion; use DSX
Connect's job recovery or a manual Full Scan for terminal scan failures.

Run one polling replica/worker. The lab deployment uses Recreate so old/new pollers do
not overlap while sharing the SQLite state. Polling uses full attachment enumeration of
selected scopes; this is intended for the small allowlisted demo, not tenant-wide scale.
JQL search indexing can delay new attachments beyond a single polling interval.

For the demo, upload a harmless attachment to **RD-28133**, then check Scan Results
for a new connector-monitor job. No Jira upload/delete/comment operations are performed
by the connector.

Polling validation: all 50 Jira/UI tests passed. The lab monitor baselined five currently
eligible attachments, then a controlled checkpoint replay of one approved attachment
created job `job_def0d3fd91cc432ca0f27e860e4de105`, which completed with a Benign verdict.
The replay changed only local checkpoint state; no Jira attachment was uploaded or changed.

## Browsing all accessible spaces and scanning selected issues

`DSXCONNECTOR_JIRA_DISCOVER_SPACES=true` enables paginated `GET /project/search`
discovery. This reads project metadata only; it does not enumerate issues or download
attachments from every discovered space. A token with classic `read:jira-work` covers
the Jira read endpoints. No project/issue write permission is needed. This flag is enabled in the lab; the replacement read token was verified against both
space discovery and approved-issue search (58 accessible spaces).

In demo mode, RD is labeled with its selected issue keys. Other accessible spaces are
labeled **Demo scans disabled** unless their issues are added to the deployment allowlist.
Discovery does not create protected scopes. Choosing Protect affects DSX Connect state,
not Jira configuration; scans and polling still apply the deployment's issue allowlist.

Protected Jira rows include **Scan issues**. Enter comma-separated issue keys. The API
validates the keys and intersects them with the protected scope; the connector additionally
intersects every search with its demo allowlist. The numeric attachment location remains
separate from its original filename. Selecting issues with no eligible attachments returns
a clear error rather than falling back to a broader scan.

All Jira client calls remain HTTP GET requests. Neither discovery, Protect, manual scans,
nor polling writes to Jira. They do consume normal Jira read API capacity; only eligible
attachments are downloaded to the configured scanner.
