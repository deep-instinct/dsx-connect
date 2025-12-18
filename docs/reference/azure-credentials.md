# Azure Credentials for DSX Connectors

The following guidance is for adding a connector as an app in Azure, retrieving credentials, and assigning permissions. The workflow is identical for the M365 Mail (Outlook), SharePoint, and OneDrive connectors; only the Microsoft Graph permissions differ.

> Guidance current as of 2025-10-27. Azure portal labels occasionally change; adjust as needed if the UI differs.

## Portal Workflow

1. **Sign in to Azure**  
   Browse to [https://portal.azure.com](https://portal.azure.com) and sign in with an account that can register applications (Application Administrator or Global Administrator).

2. **Locate Tenant ID**  
   In the header, ensure you are in the correct directory. Copy the “Tenant ID” shown under *Directory + subscription*. This becomes `M365_TENANT_ID` (or the equivalent setting for other connectors).

3. **Register the Application**  
   - Go to *Microsoft Entra ID → App registrations → New registration*.  
   - Name the app (e.g., `dsx-m365-mail-connector`).  
   - Leave the default single-tenant option.  
   - Redirect URIs are optional for client credentials.  
   - Click *Register*.  
   On the Overview blade, copy the **Application (client) ID** (`M365_CLIENT_ID`).

4. **Create a Client Secret**  
   - Navigate to *Certificates & secrets*.  
   - Add a new client secret, note the expiration, and copy the **Value** immediately (`M365_CLIENT_SECRET`). You cannot retrieve it later.

5. **Assign Microsoft Graph Application Permissions**  
   - Open *API permissions* → *Add a permission* → *Microsoft Graph* → *Application*.  
   - Select the permissions your connector needs (see [Required Microsoft Graph permissions](#required-microsoft-graph-permissions)).  
   - After adding them, click *Grant admin consent* and approve.

6. **Optional Adjustments**  
   - Configure redirect URIs only if you plan to use interactive flows.  
   - Use certificates instead of secrets if your security policy requires it.

Record the tenant ID, client ID, and secret securely (Azure Key Vault, Kubernetes Secret, etc.) before proceeding with connector deployment.

## Required Microsoft Graph permissions

### M365 Mail connector (Outlook / Exchange Online)

Grant these application permissions when running the Outlook/M365 Mail connector:

| Permission | Purpose |
|------------|---------|
| `Mail.Read` | Inspect message metadata, check for attachments, and run delta queries. |
| `Mail.ReadWrite` | Remove attachments, tag subjects, and move/quarantine malicious messages. |
| `Files.Read.All` | Required by Graph when downloading attachments exposed as drive items. |

If you disable remediation actions, you may omit `Mail.ReadWrite`, but keep it if you expect the connector to modify messages.

### SharePoint connector

Grant these application permissions when running the SharePoint connector:

| Permission | Purpose |
|------------|---------|
| `Sites.Read.All` | Discover SharePoint sites, enumerate drives, and create change-notification subscriptions. |
| `Files.Read.All` | Enumerate files and stream content to dsx-connect for scanning. |
| `Files.ReadWrite.All` | Needed when MOVE or DELETE item actions are enabled. |

If you use the connector strictly for read-only scanning, you can omit `Files.ReadWrite.All`, but leave it enabled if remediation actions are planned.

### OneDrive connector

Grant these application permissions when running the OneDrive connector:

| Permission | Purpose |
|------------|---------|
| `Files.Read.All` | Enumerate files and stream content from users' OneDrive accounts. |
| `Files.ReadWrite.All` | Required if you plan to delete or move items after verdicts. |

If your deployment is read-only, you can omit `Files.ReadWrite.All`, but keep it when item actions are enabled.

## Automation with Azure CLI

The Azure CLI can create the application and add permissions programmatically. Choose the permission set that matches your connector:

- M365 Mail: `Mail.Read`, `Mail.ReadWrite`, `Files.Read.All`
- SharePoint: `Sites.Read.All`, `Files.Read.All`, `Files.ReadWrite.All`
- OneDrive: `Files.Read.All`, `Files.ReadWrite.All`

```bash
TENANT_ID=$(az account show --query tenantId -o tsv)
# Pick a descriptive name per connector, e.g., dsx-m365-mail-connector or dsx-sharepoint-connector
# Pick an app name per connector, e.g., dsx-m365-mail-connector, dsx-sharepoint-connector, dsx-onedrive-connector
APP_NAME="dsx-m365-mail-connector"
APP=$(az ad app create --display-name "$APP_NAME" --query "{appId:appId,objectId:id}" -o json)
CLIENT_ID=$(echo "$APP" | jq -r .appId)
SECRET=$(az ad app credential reset --id "$CLIENT_ID" --display-name dsx-connector --years 2 \
         --query "{secret:password}" -o json | jq -r .secret)
```

### Assign permissions for M365 Mail

```bash
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
MAIL_READ_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Mail.Read' && contains(allowedMemberTypes, 'Application')].id" -o tsv)
MAIL_READWRITE_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Mail.ReadWrite' && contains(allowedMemberTypes, 'Application')].id" -o tsv)
FILES_READ_ALL_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Files.Read.All' && contains(allowedMemberTypes, 'Application')].id" -o tsv)

ROLE_IDS=("$MAIL_READ_ID" "$MAIL_READWRITE_ID" "$FILES_READ_ALL_ID")
PERMISSIONS=()
for ROLE_ID in "${ROLE_IDS[@]}"; do
  [ -n "$ROLE_ID" ] && PERMISSIONS+=("${ROLE_ID}=Role")
done

if [ ${#PERMISSIONS[@]} -gt 0 ]; then
  az ad app permission add --id "$CLIENT_ID" --api "$GRAPH_APP_ID" \
    --api-permissions "${PERMISSIONS[@]}"
fi

az ad sp create --id "$CLIENT_ID"
az ad app permission admin-consent --id "$CLIENT_ID"

echo "Tenant ID: $TENANT_ID"
echo "Client ID: $CLIENT_ID"
echo "Client Secret: $SECRET"
```

### Assign permissions for SharePoint

If you create a separate application for the SharePoint connector, repeat the `APP_NAME`/creation step with a new value (for example `dsx-sharepoint-connector`). Otherwise, reuse the same `CLIENT_ID`.

```bash
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
SITES_READ_ALL_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Sites.Read.All' && contains(allowedMemberTypes, 'Application')].id" -o tsv)
FILES_READ_ALL_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Files.Read.All' && contains(allowedMemberTypes, 'Application')].id" -o tsv)
FILES_READWRITE_ALL_ID=$(az ad sp show --id "$GRAPH_APP_ID" \
  --query "appRoles[?value=='Files.ReadWrite.All' && contains(allowedMemberTypes, 'Application')].id" -o tsv)

ROLE_IDS=("$SITES_READ_ALL_ID" "$FILES_READ_ALL_ID" "$FILES_READWRITE_ALL_ID")
PERMISSIONS=()
for ROLE_ID in "${ROLE_IDS[@]}"; do
  [ -n "$ROLE_ID" ] && PERMISSIONS+=("${ROLE_ID}=Role")
done

if [ ${#PERMISSIONS[@]} -gt 0 ]; then
  az ad app permission add --id "$CLIENT_ID" --api "$GRAPH_APP_ID" \
    --api-permissions "${PERMISSIONS[@]}"
fi

az ad sp create --id "$CLIENT_ID"
az ad app permission admin-consent --id "$CLIENT_ID"

echo "Tenant ID: $TENANT_ID"
echo "Client ID: $CLIENT_ID"
```

- `az ad app permission grant` is designed for delegated scopes and requires `--scope`; for application permissions you can skip it.  
- If `az ad app permission admin-consent` fails with `Consent validation failed`, use either the Azure portal or the Graph API approach described below.  
- Secrets created with `az ad app credential reset` expire automatically; adjust `--years` as needed and rotate before expiry.

## Troubleshooting Admin Consent

Some tenants block the legacy Azure AD Graph endpoint that the CLI uses for admin consent. Two reliable alternatives:

1. **Azure Portal** – Go to *App registrations → API permissions → Grant admin consent* and approve the dialog.  
2. **Microsoft Graph API** – Assign each app role directly:

Reuse the `ROLE_IDS` array from the snippet above (ensure it includes every role you granted).

```bash
APP_SP=$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)
GRAPH_SP=$(az ad sp show --id "$GRAPH_APP_ID" --query id -o tsv)

for ROLE_ID in "${ROLE_IDS[@]}"; do
  [ -n "$ROLE_ID" ] || continue
  az rest --method POST \
    --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$APP_SP/appRoleAssignments" \
    --body "{\"principalId\":\"$APP_SP\",\"resourceId\":\"$GRAPH_SP\",\"appRoleId\":\"$ROLE_ID\"}"
done
```

Replace or extend the `ROLE_ID` list to match the permissions you added earlier.

Once the assignments succeed, verify with:

```bash
az ad app permission list --id "$CLIENT_ID" --show-resource-name --query "[].{resource:resourceDisplayName,scope:resourceAccess[].id}"
```

The permissions should show `isEnabled: true`. You can now supply the tenant ID, client ID, and client secret to the DSX connector (M365 Mail or SharePoint) that authenticates against Microsoft Graph.
