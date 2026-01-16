# Docker Compose Best Practices

Think of the Compose YAML as a template and `.env` files as the fill. Keep the YAML stable; swap `.env` files per environment (dev/stage/prod) to pin image tags and inject secrets without editing YAML.

## Prerequisites
- Docker Desktop / Docker Engine with the Compose plugin.
- The dsx-connect Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`) downloaded and extracted locally. Bundles are published at [dsx-connect releases](https://github.com/deep-instinct/dsx-connect/releases).

## Core ideas in this guide
- Use `.env` files to pin images. Avoid editing `docker-compose-*.yaml`.
- Maintain one env file per environment: `.dev.env`, `.stage.env`, `.prod.env`.
- Pin all images in the env file (core, DSXA, connectors) so you know exactly what you’re running.
- Reuse the same env files when you move to Kubernetes (convert to a Secret).
- For environment settings and worker retry policies, see [Deployment Advanced Settings](../advanced.md).

### Sample `.env`
```bash
# Core + DSXA images (pin releases)
DSXCONNECT_IMAGE=dsxconnect/dsx-connect:1.2.3
DSXA_IMAGE=dsxconnect/dpa-rocky9:4.1.1.2020

# Connector image example
ONEDRIVE_IMAGE=dsxconnect/onedrive-connector:0.1.7
```

## Secrets and Credentials
Connectors typically require credentials to access external file repositories, typically in the form of an access key or secret
(and usually a combination of things like tenant ID, client ID, and client secret). As these are sensitive credentials, they should be stored
and/or handled securely.

In the following guides on deploying connectors we will use `.env` files to supply credentials. While easy for
deployment purposes, using a secrets manager is more ideal for production use.

If you must use a local env file for Docker Compose:

- Never commit it: keep real secrets only in local `.env`/`.core.env` files and ensure they’re in `.gitignore`.
- Restrict file permissions: `chmod 600 .env`.
- Treat it as ephemeral: create it only for the duration of the deployment run, and delete it when you’re done.
- Rotate credentials regularly
- Avoid copying into tickets/docs: share only sample files (e.g., `.sample.*.env`) with blanks/placeholders.
- Add a pre-flight secret scan before publishing: e.g., run `rg` for common patterns or use tooling like `trufflehog`/`git-secrets`.

If you can use a secrets manager, we recommend it.

Good options for secret management for Docker deployments include:

- Cloud-native: AWS Secrets Manager, Azure Key Vault, Google Secret Manager
- Self-hosted: HashiCorp Vault
- Developer tooling: 1Password CLI, Doppler

For long-running or shared environments, Kubernetes is strongly recommended:

- Kubernetes Secrets (and/or Sealed Secrets / SOPS) keep credentials out of your repo.
- External Secrets Operator can sync from AWS/Azure/GCP secret managers automatically.
- Deployments can consume secrets via `envFrom` or mounted files with least-privilege RBAC.

## TLS Certificates (Local Dev)
For local development, prefer **mounting** TLS certs at runtime instead of baking them into images. Baking a private key into an image makes it easy to accidentally publish it (for example, by pushing the image to a registry).

### Generate a local dev cert (SANs for `localhost` and `dsx-connect-api`)
From the bundle root (example path `dsx-connect-<core_version>/`):
```bash
mkdir -p dsx-connect-<core_version>/certs
openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout dsx-connect-<core_version>/certs/server.key \
  -out dsx-connect-<core_version>/certs/server.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:dsx-connect-api,IP:127.0.0.1"
```

Notes:
- You may need OpenSSL (not LibreSSL) for `-addext` on macOS: `brew install openssl` and use `$(brew --prefix openssl)/bin/openssl`.
- This is for local dev only; use a real certificate (or cert-manager) for production.

### Mount certs into Compose
Create an override file next to the compose files (bundle root):
```yaml
# dsx-connect-<core_version>/docker-compose.tls.override.yaml
services:
  dsx_connect_api:
    volumes:
      - ./certs:/app/certs:ro
```

Then enable TLS via env and start the stack:
```bash
# in dsx-connect-<core_version>/.core.env
# DSXCONNECT_USE_TLS=true
# DSXCONNECT_TLS_CERTFILE=/app/certs/server.crt
# DSXCONNECT_TLS_KEYFILE=/app/certs/server.key

docker compose --env-file dsx-connect-<core_version>/.core.env \
  -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml \
  -f dsx-connect-<core_version>/docker-compose.tls.override.yaml up -d
```

For connectors, use the same pattern: mount `./certs:/app/certs:ro` into the connector service and set `DSXCONNECTOR_USE_TLS=true` plus `DSXCONNECTOR_TLS_CERTFILE`/`DSXCONNECTOR_TLS_KEYFILE`. If the connector talks to dsx-connect over HTTPS with a self-signed cert, set `DSXCONNECTOR_CA_BUNDLE=/app/certs/server.crt` (or disable verification only for local dev).


## Deployment Example: OneDrive Connector
1. Download and extract the Docker Compose bundle (`dsx-connect-compose-bundle-<core_version>.tar.gz`), which expands to `dsx-connect-<core_version>/`.
2. Copy the core sample env: `cp dsx-connect-<core_version>/.sample.core.env example.core.env`. 
3. Run DSXA if needed:
```bash
docker compose --env-file example.core.env -f dsx-connect-<core_version>/docker-compose-dsxa.yaml up -d
```
4. Run core (example):  
   ```bash
   docker network create dsx-connect-network || true
   docker compose --env-file example.core.env -f dsx-connect-<core_version>/docker-compose-dsx-connect-all-services.yaml up -d
   ```
5. Copy the connector sample env: `cp dsx-connect-<core_version>/onedrive-connector-<connector_version>/.sample.onedrive.env example.onedrive.env`.
6. Edit `example.onedrive.env` (tenant/client creds, asset, etc.)
   ```dotenv
    # Env for OneDrive connector. Pin the image and set Tenant, Client ID, Client Secret, User and Asset. 
    
    # OneDrive connector env (sample)
    ONEDRIVE_IMAGE=dsxconnect/onedrive-connector:0.1.13
    ONEDRIVE_TENANT_ID=
    ONEDRIVE_CLIENT_ID=
    ONEDRIVE_CLIENT_SECRET=
    ONEDRIVE_USER_ID=
    DSXCONNECTOR_ASSET=/Documents/dsx-connect
    DSXCONNECTOR_FILTER=
    #DSXCONNECT_ENROLLMENT_TOKEN=abc123
   ```
5. Deploy the OneDrive connector:  
   ```bash
   docker compose --env-file example.onedrive.env \
     -f dsx-connect-<core_version>/onedrive-connector-<connector_version>/docker-compose-onedrive-connector.yaml up -d
   ```



## Reuse for Kubernetes
Create a Secret from the same env file and reference it in Helm values:
```bash
kubectl create secret generic dsxconnect-env --from-env-file=.prod.env -n your-namespace
# In values.yaml (core + connectors):
# envSecretRefs:
#   - dsxconnect-env
```
This keeps configuration consistent across Compose and K8s.

## Tips
- Keep secrets out of YAML; store them in env files or your secret manager.
- Pin tags in env files; avoid `:latest` for anything shared.
- Use separate env files per environment; commit only samples (`*.env.sample`), not real secrets.
- For TLS, mount your CA bundle and set `DSXCONNECTOR_VERIFY_TLS=true` and `DSXCONNECTOR_CA_BUNDLE=...`.
