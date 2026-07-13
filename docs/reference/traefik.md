# Traefik Reference

Traefik is commonly installed by default with k3s and can serve Kubernetes `Ingress` resources for lab deployments. Treat this page as a k3s / Traefik reference pattern; production ingress is often dictated by your Kubernetes platform, load balancer, WAF, or gateway standard.

## Check Traefik

Confirm Traefik is running:

```bash
kubectl get pods -n kube-system -l app.kubernetes.io/name=traefik
kubectl get ingressclass
```

Most k3s installs expose an ingress class named `traefik`. Use that value as `ingress.className` in chart values.

## Hostnames

For a lab host at `10.2.4.103`, `nip.io` can provide DNS without creating a real zone:

```text
dsx-connect.10.2.4.103.nip.io
```

`nip.io` only resolves the name to the IP address. Ports `80` and `443` still need to be reachable on the cluster host or load balancer where Traefik is listening.

## TLS Secret

If Traefik terminates HTTPS, create the TLS secret in the same namespace as the `Ingress`.

For a lab self-signed certificate:

```bash
export NAMESPACE=dsx-connect
export HOST=dsx-connect.10.2.4.103.nip.io

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout tls-k3s.key \
  -out tls-k3s.crt \
  -days 365 \
  -subj "/CN=$HOST" \
  -addext "subjectAltName=DNS:$HOST"

kubectl create secret tls dsx-connect-tls \
  -n "$NAMESPACE" \
  --cert=tls-k3s.crt \
  --key=tls-k3s.key
```

Verify it:

```bash
kubectl get secret -n "$NAMESPACE" dsx-connect-tls
```

## HTTP To HTTPS Redirects

k3s installs Traefik through a managed Helm chart in `kube-system`. To redirect all HTTP traffic on Traefik to HTTPS, create a `HelmChartConfig`:

```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: traefik
  namespace: kube-system
spec:
  valuesContent: |-
    ports:
      web:
        port: 80
      websecure:
        port: 443
    additionalArguments:
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
```

Apply it and restart Traefik:

```bash
kubectl apply -f traefik-https-redirect.yaml
kubectl rollout restart deployment/traefik -n kube-system
kubectl rollout status deployment/traefik -n kube-system
```

Verify redirect behavior:

```bash
curl -I http://dsx-connect.10.2.4.103.nip.io/
```

Expected: an HTTP redirect status such as `301` or `308` and a `Location` header pointing to `https://...`.

## Troubleshooting

Check the rendered ingress:

```bash
kubectl get ingress -n dsx-connect
kubectl describe ingress -n dsx-connect dsx-connect-api
```

Check Traefik logs:

```bash
kubectl logs -n kube-system deploy/traefik --tail=100
```

If the host resolves but the browser cannot connect, verify that ports `80` and `443` are reachable on the lab host and that the ingress host matches the hostname in the browser exactly.
