# Walkthrough: Deploying Full Stack with Authentication and TLS

This walkthrough deploys a full stack in Kubernetes using **Method 1** (OCI charts + CLI overrides):

- dsx-connect core (API + workers + Redis)
- DSXA scanner (in-cluster, optional)
- Azure Blob Storage connector

It also enables:

- **DSX-Connect Authentication** (enrollment token + DSX-HMAC)
- **SSL/TLS** for the dsx-connect API (in-pod TLS)

For production-style values files and GitOps patterns, see [Advanced Connector Deployment](advanced-connector-deployment.md) and [Using DSX-Connect Authentication](../authentication.md).

## Prerequisites

- Kubernetes 1.19+ cluster (Colima with `--kubernetes` works well for local runs).
- Helm 3.2+, kubectl, access to Docker Hub (`helm registry login registry-1.docker.io`).
- Azure storage connection string for a test container with sample files.
- DSXA appliance URL, token, and scanner ID.

## 1) Set variables

```bash
export NAMESPACE=dsx-walkthrough-tls-auth
export RELEASE=dsx-walkthrough
export CONNECTOR_RELEASE=azure-connector

# Pin chart/image versions for reproducibility
export CORE_CHART_VERSION="<core-chart-version>"
export CORE_IMAGE_TAG="<core-image-tag>"                   # typically matches chart appVersion
export AZURE_CHART_VERSION="<azure-connector-chart-version>"
export AZURE_IMAGE_TAG="<azure-connector-image-tag>"

# Authentication (shared enrollment token)
export ENROLLMENT_TOKEN="$(uuidgen)"

# DSXA (if using the in-cluster dsxa-scanner)
export DSXA_APPLIANCE_URL="https://<di>.customers.deepinstinctweb.com"
export DSXA_SCANNER_ID="1"
export DSXA_TOKEN="<dsxa-token>"

# Azure Blob connector
export AZURE_CONTAINER="mytestcontainer"
export AZURE_STORAGE_CONNECTION_STRING="<azure-connection-string>"
```

```bash
kubectl create namespace $NAMESPACE
```

## 2) Create Secrets (Authentication, TLS, Azure creds)

### Enrollment token secret (dsx-connect auth)
```bash
kubectl create secret generic ${RELEASE}-dsx-connect-api-auth-enrollment \
  --from-literal=ENROLLMENT_TOKEN="${ENROLLMENT_TOKEN}" \
  -n ${NAMESPACE}
```

### TLS secret for dsx-connect API (in-pod TLS)
Generate a quick self-signed cert (local dev only), then create the Secret:
```bash
TMPDIR="$(mktemp -d)"
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout "${TMPDIR}/tls.key" \
  -out "${TMPDIR}/tls.crt" \
  -subj "/CN=dsx-connect-api" \
  -addext "subjectAltName=DNS:dsx-connect-api,DNS:localhost,IP:127.0.0.1"

kubectl create secret tls ${RELEASE}-dsx-connect-api-tls \
  --cert="${TMPDIR}/tls.crt" --key="${TMPDIR}/tls.key" \
  -n ${NAMESPACE}
```

### Azure connection string secret
```bash
kubectl create secret generic azure-storage-connection-string \
  --from-literal=AZURE_STORAGE_CONNECTION_STRING="${AZURE_STORAGE_CONNECTION_STRING}" \
  -n ${NAMESPACE}
```

## 3) Install dsx-connect core (TLS + auth)
This installs from the OCI chart and enables:
- API TLS (service port 443)
- Enrollment auth
- In-cluster DSXA scanner

```bash
helm upgrade --install ${RELEASE} oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version ${CORE_CHART_VERSION} \
  -n ${NAMESPACE} --create-namespace \
  --set-string global.image.tag=${CORE_IMAGE_TAG} \
  --set dsxa-scanner.enabled=true \
  --set-string dsxa-scanner.env.APPLIANCE_URL=${DSXA_APPLIANCE_URL} \
  --set-string dsxa-scanner.env.TOKEN=${DSXA_TOKEN} \
  --set-string dsxa-scanner.env.SCANNER_ID=${DSXA_SCANNER_ID} \
  --set dsx-connect-api.auth.enabled=true \
  --set dsx-connect-api.tls.enabled=true \
  --set dsx-connect-api.service.port=443
```

## 4) Install the Azure Blob connector (auth enabled)
This enables connector-side auth and points the connector at the in-cluster dsx-connect API over HTTPS.

For local demo TLS, verification against a self-signed dsx-connect cert will fail unless you provide a CA bundle. For simplicity this walkthrough disables verification; for production, see [Deploying with SSL/TLS](../tls.md).

```bash
helm upgrade --install ${CONNECTOR_RELEASE} oci://registry-1.docker.io/dsxconnect/azure-blob-connector-chart \
  --version ${AZURE_CHART_VERSION} \
  -n ${NAMESPACE} \
  --set-string image.tag=${AZURE_IMAGE_TAG} \
  --set-string env.DSXCONNECTOR_ASSET=${AZURE_CONTAINER} \
  --set-string env.DSXCONNECTOR_FILTER=\"\" \
  --set-string env.DSXCONNECTOR_DSX_CONNECT_URL=\"https://dsx-connect-api\" \
  --set-string env.DSXCONNECTOR_VERIFY_TLS=\"false\" \
  --set auth_dsxconnect.enabled=true \
  --set-string auth_dsxconnect.enrollmentSecretName=${RELEASE}-dsx-connect-api-auth-enrollment \
  --set-string auth_dsxconnect.enrollmentKey=ENROLLMENT_TOKEN \
  --set-string secrets.name=azure-storage-connection-string
```

## 5) Verify
```bash
kubectl get pods -n ${NAMESPACE}
kubectl get svc -n ${NAMESPACE}
```

Port-forward the TLS service and open the UI:
```bash
kubectl port-forward -n ${NAMESPACE} svc/dsx-connect-api 8586:443
```

Then browse to `https://localhost:8586` (self-signed cert warning is expected).

## Cleanup

```bash
helm uninstall ${CONNECTOR_RELEASE} -n ${NAMESPACE}
helm uninstall ${RELEASE} -n ${NAMESPACE}
kubectl delete namespace ${NAMESPACE}
```
