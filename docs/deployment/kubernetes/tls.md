# Enabling TLS (Kubernetes)

In Kubernetes, TLS is most commonly terminated at the Ingress (or LoadBalancer) layer. DSX-Connect also supports application-level TLS at the `dsx-connect-api` pod when encryption directly to the service is required.

For conceptual background, see:
[Concepts → TLS](../../concepts/tls.md)

## Choosing a TLS Mode

### Ingress TLS Termination (Recommended)

Flow:

Client → HTTPS → Ingress → HTTP → DSX-Connect Service

Use this when:

* You are using an ingress controller (nginx, Traefik, ALB, OpenShift Route, etc.)
* You want centralized certificate management
* You are using cert-manager
* You want minimal application-level configuration

This is the preferred approach for most production deployments.

### DSX-Connect API TLS (Application-Level TLS)

Flow:

Client → HTTPS → DSX-Connect API Pod → Service

Use this when:

* You are not terminating TLS at ingress
* You require HTTPS directly at the API service
* You need encryption all the way to the pod

This mode uses a Kubernetes TLS Secret mounted into the `dsx-connect-api` pod.

You can technically combine both modes, but that requires ingress backend HTTPS configuration and is rarely necessary.

## Ingress TLS Termination

### Step 1: Create or Reference a TLS Secret

If you already have a certificate and key:

```bash
kubectl create secret tls dsx-connect-tls \
  --cert=cert.pem \
  --key=key.pem \
  -n <namespace>
```

If using cert-manager, create a `Certificate` resource and reference the generated Secret in your Ingress configuration.

### Step 2: Enable Ingress in Helm

Example values:

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: dsx.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: dsx-connect-tls
      hosts:
        - dsx.example.com
```

Deploy:

```bash
helm upgrade --install <release> \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  -n <namespace> \
  -f values.yaml
```

### Step 3: Verify

```bash
kubectl get ingress -n <namespace>
```

Open:

[https://dsx.example.com](https://dsx.example.com)

Confirm:

* Certificate is valid
* UI loads over HTTPS
* Browser shows secure lock icon

## DSX-Connect API TLS (Application-Level)

### Step 1: Create the TLS Secret Expected by the Chart

The chart expects the Secret name:

`<release>-dsx-connect-api-tls`

Example for release `dsx` in namespace `dsx-connect`:

`dsx-dsx-connect-api-tls`

If you already have `tls.crt` and `tls.key` files:

```bash
kubectl create secret tls dsx-dsx-connect-api-tls \
  --cert=tls.crt \
  --key=tls.key \
  -n dsx-connect
```

GitOps-friendly YAML equivalent:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dsx-dsx-connect-api-tls
  namespace: dsx-connect
type: kubernetes.io/tls
data:
  tls.crt: <base64-encoded-cert>
  tls.key: <base64-encoded-key>
```

Apply:

```bash
kubectl apply -f examples/secrets/tls-secret.yaml
```

### Step 2: Enable TLS in Helm

Command-line:

```bash
helm upgrade --install dsx -n dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --set dsx-connect-api.tls.enabled=true
```

Values file:

```yaml
dsx-connect-api:
  tls:
    enabled: true
```

If your Secret name differs from the default:

```yaml
dsx-connect-api:
  tls:
    enabled: true
    secretName: my-custom-tls-secret
```

### Step 3: Verify the API

```bash
kubectl get pods -n dsx-connect
kubectl logs -n dsx-connect deploy/dsx-dsx-connect-api
```

If accessing via port-forward, use `https://` and ensure the correct port is exposed.

If using a self-signed certificate, clients must trust the issuing CA.

## Troubleshooting

### Browser shows certificate warning

Expected for self-signed certificates.
Use a trusted certificate or distribute the CA bundle to clients.

### Ingress HTTPS works but backend fails

If TLS is enabled at both ingress and the API:

* Ensure your ingress controller is configured to speak HTTPS to the backend service
* Backend protocol configuration differs by ingress controller

### API pod crashloops when TLS is enabled

Common causes:

* Secret missing
* Secret in the wrong namespace
* Secret name mismatch
* Missing `tls.crt` or `tls.key`

Check:

```bash
kubectl get secret -n dsx-connect | grep tls
kubectl describe pod -n dsx-connect <api-pod>
```

## Related Pages

* [Concepts → TLS](../../concepts/tls.md)
* [Kubernetes → Authentication](authentication.md)
* [Kubernetes → Deploying DSX-Connect (Helm)](dsx-connect.md)
