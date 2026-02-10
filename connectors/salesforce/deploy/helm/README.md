# Salesforce Connector Helm Chart (Skeleton)

This is a minimal Helm chart skeleton for deploying the connector.

- Values expose connector env via `.Values.env` (including `DSXCONNECTOR_DISPLAY_NAME`).
- TLS options are included to serve HTTPS from the connector and to verify outbound TLS to dsx-connect.

## Quickstart

1) Update image repo/tag in `values.yaml` (defaults to `dsxconnect/salesforce-connector:0.1.0`).

2) Set minimal env in `values.yaml` (ASSET/FILTER; optional DISPLAY_NAME):

```yaml
env:
  DSXCONNECTOR_ASSET: ""
  DSXCONNECTOR_FILTER: ""
  # Optional friendly name
  # DSXCONNECTOR_DISPLAY_NAME: "Salesforce Connector"
```

3) Install

```bash
helm upgrade --install salesforce-connector ./deploy/helm -n dsx --create-namespace
```

4) Port-forward and check

```bash
kubectl -n dsx port-forward svc/salesforce-connector 8080:80
open http://localhost:8080/docs
```

Notes:
- For production TLS, mount your own cert/key and set `DSXCONNECTOR_USE_TLS=true` and the `DSXCONNECTOR_TLS_*` paths accordingly.
- Outbound TLS to dsx-connect can be controlled with `DSXCONNECTOR_VERIFY_TLS` and optional `DSXCONNECTOR_CA_BUNDLE`.

## Secrets (JWT + TLS)

Create a Secret for Salesforce JWT credentials (example: `sf-secret.yaml`):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-connector-credentials
type: Opaque
stringData:
  DSXCONNECTOR_SF_AUTH_METHOD: "jwt"
  DSXCONNECTOR_SF_CLIENT_ID: "<consumer-key>"
  DSXCONNECTOR_SF_USERNAME: "dsx@customer.com"
  DSXCONNECTOR_SF_JWT_PRIVATE_KEY: "<base64-or-pem>"
```

```bash
kubectl apply -f sf-secret.yaml
```

Reference the secret in `values.yaml`:

```yaml
envSecretRefs:
  - salesforce-connector-credentials
```

Create a TLS Secret for connector HTTPS (example: `tls-secret.yaml`):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: salesforce-connector-tls
type: kubernetes.io/tls
data:
  tls.crt: <base64-cert>
  tls.key: <base64-key>
```

```bash
kubectl apply -f tls-secret.yaml
```

Enable TLS in `values.yaml` (the chart mounts the secret as `salesforce-connector-tls`):

```yaml
tls:
  enabled: true
```
