# Deploying DSX-Connect with SSL/TLS (Kubernetes)

This page covers enabling TLS for dsx-connect core and connectors when deploying with Helm/Kubernetes.

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
