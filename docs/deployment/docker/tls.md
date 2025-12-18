# Deploying with SSL/TLS (Docker Compose)

Enable HTTPS for dsx-connect core and connectors when running via Docker Compose. Favor runtime-mounted certs over baking them into images, and use real certs (or short-lived self-signed) depending on environment.

## Core (dsx-connect API/UI)
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

## Connectors (generic)
1) Mount the same certs into the connector container (service name differs per connector compose file—check under `services:`):
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
