Shared development TLS certificates for local HTTPS testing.

This folder is the *convenience location* for dev-generated TLS materials. The
certificate and key are intentionally not committed to git.

Generate them locally using either of the included scripts:
- `dsx_connect/deploy/docker/certs/generate-dev-cert.sh`
- `connectors/framework/deploy/certs/generate-dev-cert.sh`

Then copy the outputs here:
```bash
cp dsx_connect/deploy/docker/certs/dev.localhost.crt shared/deploy/certs/dev.localhost.crt
cp dsx_connect/deploy/docker/certs/dev.localhost.key shared/deploy/certs/dev.localhost.key
```

Usage examples:
- API: set `DSXCONNECT_USE_TLS=true`, point cert/key to `shared/deploy/certs/dev.localhost.{crt,key}`
- Connector (server): set `DSXCONNECTOR_USE_TLS=true` and point to the same cert/key
- Connector (client outbound): set `DSXCONNECTOR_VERIFY_TLS=true` and optionally `DSXCONNECTOR_CA_BUNDLE=shared/deploy/certs/dev.localhost.crt`

Note: the scripts generate self-signed materials for local dev only; do not use them in production.
