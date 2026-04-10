# SharePoint Connector — Docker

The **SharePoint connector** scans SharePoint Online document libraries/folders and sends files to DSX-Connect for scanning.

It supports:

* **Full scans** of a site/library/folder scope
* **Continuous monitoring** via Microsoft Graph change notifications
* **Remediation actions** such as delete, move, or tag after malicious verdicts

Monitoring uses a **subscription callback model**: the connector creates a Graph subscription, and Microsoft Graph calls the connector webhook URL when changes occur.

---

## Prerequisites

Before deploying the connector, prepare an Entra app registration for SharePoint/Graph access.

Required:

* Tenant ID, Client ID, Client Secret
* Microsoft Graph **Application** permissions (not Delegated), with admin consent
* SharePoint asset URL (`DSXCONNECTOR_ASSET`) pointing to the site/library/folder you want to scan

For credential setup details:

➡️ [Azure Credentials (M365 / SharePoint / OneDrive)](../../reference/azure-credentials.md)

---

## Minimal Deployment

The following steps install the connector with minimal changes, supporting full scan only.

!!! tip "Using the Docker bundle"

    All Docker connector deployments use the official **DSX-Connect Docker bundle**, which contains compose files and sample env files.

    [DSX-Connect Docker bundles](https://github.com/deep-instinct/dsx-connect/releases)

From the extracted bundle, navigate to:
`dsx-connect-<core_version>/sharepoint-connector-<connector_version>/`

The easiest path is to edit `sample.sharepoint.env` and deploy with `docker-compose-sharepoint-connector.yaml`.

### Set scan parameters

Minimal example:

```dotenv
# SharePoint auth
SP_TENANT_ID=...
SP_CLIENT_ID=...
SP_CLIENT_SECRET=...

# Required scan scope (full SharePoint URL to site/library/folder)
DSXCONNECTOR_ASSET=https://contoso.sharepoint.com/sites/MySite/Shared%20Documents
DSXCONNECTOR_FILTER=

# Optional remediation
DSXCONNECTOR_ITEM_ACTION=nothing
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=dsxconnect-quarantine
```

### Deploy

```bash
docker compose --env-file sample.sharepoint.env -f docker-compose-sharepoint-connector.yaml up -d
```

You should now see the connector in the DSX-Connect UI.

---

## Required Settings

{% include-markdown "shared/connectors/_required_settings_env_table.md" %}

### `DSXCONNECT_ASSET`

`DSXCONNECTOR_ASSET` defines the **SharePoint site, document library, or folder scope** to scan.

#### Finding the SharePoint Asset URL

The easiest way to obtain this value is from the SharePoint UI.

Step 1: Navigate to your content

In SharePoint:

1. Open the target site
2. Click **Documents** (or your target library)
3. Navigate to the folder you want to scan (optional)

Step 2: Copy the browser URL

Example (library view):

```text
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/Forms/AllItems.aspx
```

Step 3: Remove SharePoint UI components

Remove:

* `/Forms/AllItems.aspx`
* Any query parameters (`?id=...&viewid=...`)

Result: Use the clean content path

```text
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents
```

---

#### Subfolder example

SharePoint folder view URL:

```text
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2Fdsx%2DconnectTest%2FShared%20Documents%2Fsub1&viewid=...
```

Decoded path:

```text
/sites/dsx-connectTest/Shared Documents/sub1
```

Asset URL to use:

```text
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/sub1
```

---

#### Key rule

`DSXCONNECTOR_ASSET` should always represent the **actual SharePoint content path**, not the browser UI page.

---

#### Sharding / Multiple Scopes

To scan large environments or segment workloads, deploy multiple connectors with different asset scopes.

Example:

```text
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/Finance
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/HR
https://ndbuildings.sharepoint.com/sites/dsx-connectTest/Shared%20Documents/Engineering
```

Each connector instance will independently scan its assigned scope.

---

### `DSXCONNECT_FILTER`

Defines a rsync-like filter to apply to files and folders, such as bucket prefixes or file filters.  

* [Reference → Filter Syntax](../../reference/filters.md)

---

### `DSXCONNECTOR_ITEM_ACTION`

Defines what happens to malicious files.

Common values:

* `nothing` (report only)
* `move` (quarantine)
* `move_tag` (quarantine and tag - moves the file and adds metadata tag)`
* `delete`

If using `move`, also set:

### `DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO`

Defines an object store resource and prefix to move quarantined files to.

Using our example above:
```bash
DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO=dsx-quarantine
```
would move quarantined files to `dsx-quarantine` under the same bucket or container specified in `DSXCONNECTOR_ASSET`.

---

### Connector-specific Settings

#### SharePoint / Graph Authentication

| Variable | Description |
| --- | --- |
| `SP_TENANT_ID` | Entra tenant ID. |
| `SP_CLIENT_ID` | Entra app (client) ID. |
| `SP_CLIENT_SECRET` | Entra app client secret. |
| `SP_VERIFY_TLS` | Verify Graph TLS certificates (`true`/`false`, default `true`). |
| `SP_CA_BUNDLE` | Optional CA bundle path for outbound Graph TLS verification. |

---

### Advanced Settings

#### DSX-Connect Authentication

{% include-markdown "shared/connectors/_common_connector_authentication.md" %}

#### TLS

{% include-markdown "shared/_common_connector_docker_tls.md" %}


---

## Monitor Settings

Monitoring enables **on-access scanning** for new/updated SharePoint content.

### How It Works

When monitoring is enabled:

1. Make the SharePoint connector callback publicly reachable over HTTPS.
2. Set that public base URL in `SP_WEBHOOK_URL`.
3. The connector registers that callback URL with Microsoft Graph.
4. Microsoft Graph sends change notifications to the connector, and the connector enqueues scans for new or updated content.
5. The connector also performs delta reconciliation so missed events can still be recovered.

Required for monitoring:

| Variable | Description |
| --- | --- |
| `SP_WEBHOOK_ENABLED` | Enable SharePoint monitoring (`true`/`false`). |
| `SP_WEBHOOK_URL` | Public **HTTPS** base URL for the connector callback. Microsoft Graph must be able to reach this URL. |
| `SP_WEBHOOK_CLIENT_STATE` | Optional shared secret echoed by Graph for validation. |
| `SP_WEBHOOK_CHANGE_TYPES` | Optional change types (default `updated`). |

Notes:

* `SP_WEBHOOK_URL` should be the public base URL only. The connector appends its webhook path when it registers with Graph.
* `SP_WEBHOOK_URL` must be reachable from Microsoft Graph, so `localhost` or a Docker-only hostname will not work.
* For local demos, expose the connector through a tunnel such as `ngrok` and use that public HTTPS URL.
* Keep `DSXCONNECTOR_CONNECTOR_URL` as the internal Docker network URL for dsx-connect-to-connector traffic.
* If monitoring is disabled, full scan/manual workflows still work.

### Webhook Exposure

For external callbacks into the connector, expose or tunnel the host port mapped to `8640` (compose default).
Use that public address for `SP_WEBHOOK_URL`.

Internally, keep:

`DSXCONNECTOR_CONNECTOR_URL=http://sharepoint-connector:8640`

so DSX-Connect can reach the container over the Docker network.
