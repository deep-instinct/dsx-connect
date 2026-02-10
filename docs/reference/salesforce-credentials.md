# Salesforce Credentials

This page walks through creating Salesforce credentials for the DSX-Connect Salesforce connector. The recommended production flow is JWT Bearer (headless, SSO-friendly).

## Create a Connected App

1. In Salesforce, go to **Setup**.
2. Search for **App Manager** and click **New Connected App**.
3. Set a **Connected App Name** and **Contact Email**.
4. Under **API (Enable OAuth Settings)**:
   - Check **Enable OAuth Settings**.
   - Set a **Callback URL** (not used by the password flow, but required by Salesforce). Example: `https://localhost/callback`.
   - Add OAuth scopes:
     - `Access and manage your data (api)`
     - `Perform requests on your behalf at any time (refresh_token, offline_access)`
     - `Full access (full)` (if your org requires it for ContentVersion access)
5. Save the app.
6. From the Connected App detail page, copy:
   - **Consumer Key** -> `DSXCONNECTOR_SF_CLIENT_ID`
   - **Consumer Secret** -> `DSXCONNECTOR_SF_CLIENT_SECRET`

## Create / Select an Integration User

Use a dedicated Salesforce user with access to `ContentVersion` and any objects you want to scan.

Record:
- Username -> `DSXCONNECTOR_SF_USERNAME`
- Password -> `DSXCONNECTOR_SF_PASSWORD`

## JWT Bearer Flow (Recommended)

JWT bearer auth is headless and works whether or not your org enforces SSO/Okta.

1. In the Connected App, enable **Use digital signatures** (JWT).
2. Upload a certificate (public key) for the Connected App.
3. Generate and store the matching private key (PEM).
4. Set the following env vars:
   - `DSXCONNECTOR_SF_CLIENT_ID` (consumer key)
   - `DSXCONNECTOR_SF_AUTH_METHOD` (`jwt` or `auto`)
   - `DSXCONNECTOR_SF_USERNAME` (integration user)
   - `DSXCONNECTOR_SF_JWT_PRIVATE_KEY` (PEM or base64-encoded PEM) **or** `DSXCONNECTOR_SF_JWT_PRIVATE_KEY_FILE`
   - `DSXCONNECTOR_SF_LOGIN_URL` (prod/sandbox)
   - `DSXCONNECTOR_SF_API_VERSION`

The connector signs a JWT with the private key and exchanges it for an access token.

## Username/Password Flow (Dev/Test)

This flow is easier to set up but is less suitable for headless production deployments.

## Get the Security Token

Salesforce requires a security token when logging in from an untrusted IP range.

1. Log in as the integration user.
2. Go to **Settings** -> **Reset My Security Token**.
3. Salesforce emails the token.
4. Set the token as `DSXCONNECTOR_SF_SECURITY_TOKEN`.

The connector appends the security token to the password during OAuth login.

## Choose the Login URL

- Production: `https://login.salesforce.com`
- Sandbox: `https://test.salesforce.com`

Set this as `DSXCONNECTOR_SF_LOGIN_URL`.

## Example .dev.env (JWT)

```env
DSXCONNECTOR_SF_LOGIN_URL=https://login.salesforce.com
DSXCONNECTOR_SF_API_VERSION=v60.0
DSXCONNECTOR_SF_CLIENT_ID=3MVG9...appkey
DSXCONNECTOR_SF_USERNAME=dsx@customer.com
DSXCONNECTOR_SF_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

## Notes on SSO / Okta

If your org uses Okta or SSO and blocks username/password OAuth, use one of these flows:

- OAuth Web Server Flow with a refresh token.
- JWT Bearer Flow with a certificate and integration user.

For containerized deployments (Docker/Kubernetes), the OAuth Web Server Flow is usually the least ideal choice because it requires an interactive browser login to bootstrap the refresh token and long-lived token storage. JWT Bearer is the typical production choice for headless services and works whether or not your org enforces SSO/Okta.

Those flows require additional setup and are not yet wired into the connector configuration. If you need them, we can add support and document the exact env vars.
