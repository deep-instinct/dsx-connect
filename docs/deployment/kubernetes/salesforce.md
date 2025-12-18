# Salesforce Connector — Helm Deployment

Use this guide to deploy `salesforce-connector-chart` (under `connectors/salesforce/deploy/helm/`) to Kubernetes.

## Prerequisites

- Kubernetes 1.19+, `kubectl`, and Helm 3.2+.
- Salesforce Connected App & integration user (username/password OAuth flow).
- Access to the Helm chart (local checkout or OCI: `oci://registry-1.docker.io/dsxconnect/salesforce-connector-chart`).
- dsx-connect deployed and reachable from the connector namespace.
- For secret-handling best practices, see [Kubernetes Secrets and Credentials](getting-started.md#kubernetes-secrets-and-credentials).

## Preflight Tasks

Create a Secret containing the Salesforce credentials (replace placeholders before applying):

```yaml
# salesforce-credentials.yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-connector-credentials
type: Opaque
stringData:
  DSXCONNECTOR_SF_CLIENT_ID: "<consumer-key>"
  DSXCONNECTOR_SF_CLIENT_SECRET: "<consumer-secret>"
  DSXCONNECTOR_SF_USERNAME: "dsx@customer.com"
  DSXCONNECTOR_SF_PASSWORD: "<password>"
  DSXCONNECTOR_SF_SECURITY_TOKEN: "<optional-token>"
```

```bash
kubectl apply -f salesforce-credentials.yaml
```

The chart can project this secret via `envSecretRefs`.

## Configuration

The connector charts now share a common `values.yaml` structure so operators can reuse the same knobs across AWS/Azure/SharePoint/etc.  The major sections are:

- `image`, `imagePullSecrets`, `nameOverride/fullnameOverride`
- `service`, `tls`, and optional `ingressWebhook`/`networkPolicy`
- `env` (human-friendly defaults) plus `envSecretRefs` for projecting Kubernetes Secrets
- `auth_dsxconnect` (enrollment token + DSX-HMAC) and worker/replica scaling knobs

Refer to `connectors/salesforce/deploy/helm/values.yaml` for inline comments on each block.

Key `.Values`:

| Value | Description |
| --- | --- |
| `env.DSXCONNECTOR_CONNECTOR_URL` | Connector base URL (defaults to in-cluster service). |
| `env.DSXCONNECTOR_DSX_CONNECT_URL` | dsx-connect API URL. |
| `env.DSXCONNECTOR_ASSET` | Optional SOQL clause appended via `AND` (e.g., `ContentDocumentId = '069xx...'`). |
| `env.DSXCONNECTOR_FILTER` | Optional comma-separated extensions (`pdf,docx`). |
| `env.DSXCONNECTOR_SF_LOGIN_URL` / `env.DSXCONNECTOR_SF_API_VERSION` | Login host + REST API version. |
| `env.DSXCONNECTOR_SF_WHERE`, `env.DSXCONNECTOR_SF_FIELDS`, `env.DSXCONNECTOR_SF_ORDER_BY`, `env.DSXCONNECTOR_SF_MAX_RECORDS` | Tune the ContentVersion query/batch size. |
| `envSecretRefs` | List of Kubernetes Secret names projected via `envFrom` (use this for client ID/secret/username/password). |
| `auth_dsxconnect.enabled` | Enables DSX-HMAC verification on the connector’s private endpoints. |
| `auth_dsxconnect.enrollmentSecretName` / `.enrollmentKey` | Secret & key that provide `DSXCONNECT_ENROLLMENT_TOKEN` (should match dsx-connect). |

### Example values file

```yaml
env:
  DSXCONNECTOR_DISPLAY_NAME: "Salesforce Connector"
  DSXCONNECTOR_SF_LOGIN_URL: "https://login.salesforce.com"
  DSXCONNECTOR_SF_API_VERSION: "v60.0"
  DSXCONNECTOR_SF_WHERE: "IsLatest = true"
  DSXCONNECTOR_SF_MAX_RECORDS: "500"

envSecretRefs:
  - salesforce-connector-credentials

auth_dsxconnect:
  enabled: true
  enrollmentSecretName: dsx-connect-enrollment
  enrollmentKey: ENROLLMENT_TOKEN
```

## Deployment Methods

### OCI chart with CLI overrides

```bash
helm install salesforce \
  oci://registry-1.docker.io/dsxconnect/salesforce-connector-chart \
  --version <chart-version> \
  --set-string env.DSXCONNECTOR_SF_LOGIN_URL=https://login.salesforce.com \
  --set envSecretRefs[0]=salesforce-connector-credentials \
  --set auth_dsxconnect.enabled=true \
  --set auth_dsxconnect.enrollmentSecretName=dsx-connect-enrollment
```

### Local chart (edit values)

```bash
helm pull oci://registry-1.docker.io/dsxconnect/salesforce-connector-chart --version <chart-version>
tar -xzf salesforce-connector-chart-<chart-version>.tgz
helm install salesforce ./salesforce-connector-chart -f values-salesforce.yaml
```

### GitOps / Production

Check your values file into Git (with secrets stored in Kubernetes or an external secret manager) and let Argo CD/Flux sync from the OCI chart:

```bash
helm upgrade --install salesforce-prod \
  oci://registry-1.docker.io/dsxconnect/salesforce-connector-chart \
  --version <chart-version> \
  -f values-prod.yaml
```

## Verification

```bash
helm list
kubectl get pods
kubectl logs deploy/salesforce-connector -f
```

- The pod should reach `READY`.
- In the dsx-connect UI, the Salesforce connector card should show `READY`.
- Run a test full scan and confirm ContentVersions queue properly.

## Secret Rotation & TLS

- Rotate Salesforce secrets by updating the Kubernetes Secret and restarting the connector deployment (`kubectl rollout restart deploy/salesforce-connector`).
- To serve the connector over HTTPS, set `env.DSXCONNECTOR_USE_TLS=true` and provide TLS cert/key via extra secrets or volumes.
- For dsx-connect auth, keep enrollment tokens short-lived and rotate DSX-HMAC credentials by re-registering the connector.
