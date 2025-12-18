# Deploying DSX-Connect with SSL/TLS

This page describes how to enable SSL/TLS for:
- **dsx-connect core** (API/UI)
- **Connectors** (their own HTTPS server + HTTPS calls back to dsx-connect)

Principles:
- Prefer **runtime-mounted** certificates/keys over baking them into container images.
- Use a **real certificate** (or cert-manager) for any shared/staging/production environment.
- For local dev, use **short-lived self-signed certs** and mount them only on the machine that needs them.

## Docker Compose

### Core (dsx-connect API/UI)
1) Generate a local dev certificate (example SANs for `localhost` and `dsx-connect-api`):
```bash
mkdir -p dsx-connect-<core_version>/certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout dsx-connect-<core_version>/certs/server.key \
  -out dsx-connect-<core_version>/certs/server.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:dsx-connect-api,IP:127.0.0.1"
```

macOS note: you may need Homebrew OpenSSL for `-addext`:
```bash
brew install openssl
$(brew --prefix openssl)/bin/openssl version
```

2) Mount certs into the API container using a Compose override:
```yaml
# dsx-connect-<core_version>/docker-compose.tls.override.yaml
services:
  dsx_connect_api:
    volumes:
      - ./certs:/app/certs:ro
```

3) Enable TLS via env and start:
```dotenv
# dsx-connect-<core_version>/.core.env
DSXCONNECT_USE_TLS=true
DSXCONNECT_TLS_CERTFILE=/app/certs/server.crt
DSXCONNECT_TLS_KEYFILE=/app/certs/server.key
```

```bash
docker compose --env-file dsx-connect-<core_version>/.core.env \
  -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml \
  -f dsx-connect-<core_version>/docker-compose.tls.override.yaml up -d
```

### Connectors (generic)
1) Mount the same certs into the connector container (the service name differs per connector compose file—look under the `services:` key):
```yaml
# dsx-connect-<core_version>/<connector>-connector-<connector_version>/docker-compose.tls.override.yaml
services:
  <connector_service_name>:
    volumes:
      - ../certs:/app/certs:ro
```

2) Enable connector HTTPS and (optionally) trust dsx-connect’s self-signed cert:
```dotenv
# dsx-connect-<core_version>/<connector>-connector-<connector_version>/.env
DSXCONNECTOR_USE_TLS=true
DSXCONNECTOR_TLS_CERTFILE=/app/certs/server.crt
DSXCONNECTOR_TLS_KEYFILE=/app/certs/server.key

# If dsx-connect is also running with a self-signed cert and the connector calls it over HTTPS:
DSXCONNECTOR_VERIFY_TLS=true
DSXCONNECTOR_CA_BUNDLE=/app/certs/server.crt
```

3) Start the connector with both compose files:
```bash
docker compose --env-file dsx-connect-<core_version>/<connector>-connector-<connector_version>/.env \
  -f dsx-connect-<core_version>/<connector>-connector-<connector_version>/docker-compose-<connector>.yaml \
  -f dsx-connect-<core_version>/<connector>-connector-<connector_version>/docker-compose.tls.override.yaml up -d
```

## Kubernetes (Helm)

### Core (dsx-connect API/UI)
The dsx-connect Helm chart supports TLS directly in the API pod via `dsx-connect-api.tls.enabled`. When enabled:
- The chart mounts a TLS Secret at `/app/certs`
- Uvicorn starts with `--ssl-certfile /app/certs/tls.crt` and `--ssl-keyfile /app/certs/tls.key`

1) Create the TLS secret:
```bash
kubectl create secret tls <release>-dsx-connect-api-tls \
  --cert=tls.crt --key=tls.key -n <namespace>
```

2) Enable TLS in values:
```yaml
dsx-connect-api:
  service:
    port: 443
  tls:
    enabled: true
    # secretName defaults to <release>-dsx-connect-api-tls
```

3) Install/upgrade:
```bash
helm upgrade --install <release> oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version <chart-version> \
  -n <namespace> --create-namespace \
  -f values.yaml
```

If you terminate TLS at an Ingress (common in production), keep pod TLS disabled and configure TLS at the Ingress layer using your ingress controller and cert-manager.

### Connectors (generic)
Connector charts generally support:
- `tls.enabled: true` (serves HTTPS on `443` in the pod)
- A per-release Secret named `<release>-tls` mounted at `/app/certs` (unless overridden by the chart)

1) Create the connector TLS Secret:
```bash
kubectl create secret tls <connector-release>-tls \
  --cert=tls.crt --key=tls.key -n <namespace>
```

2) Enable TLS in connector values:
```yaml
tls:
  enabled: true
env:
  DSXCONNECTOR_TLS_CERTFILE: "/app/certs/tls.crt"
  DSXCONNECTOR_TLS_KEYFILE: "/app/certs/tls.key"
```

If the connector must call dsx-connect over HTTPS with a private CA, also set:
```yaml
env:
  DSXCONNECTOR_VERIFY_TLS: "true"
  DSXCONNECTOR_CA_BUNDLE: "/app/certs/ca.pem"
```
