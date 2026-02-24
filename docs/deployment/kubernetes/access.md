# Access (port-forward/ingress)

For the following examples, we will assume the kubernetes cluster is installed on a host `10.2.4.103`.   Substitute your own IP address as needed.

## Port-forward for quick access

For local testing, port-forward the API service and open the UI in a browser:

* localhost only (default)
    * By default, kubectl port-forward binds to 127.0.0.1 only (localhost).
```bash
kubectl port-forward -n dsx-connect svc/dsx-connect-api 8080:80
```

Then open:
`http://127.0.0.1:8080/`

* To make reachable from other machines on the same subnet (bind to all interfaces)
    * --address 0.0.0.0 exposes the port on all interfaces—make sure your VM firewall/security rules allow (and that you’re okay exposing it on the network).
```bash
kubectl port-forward -n dsx-connect svc/dsx-connect-api 8080:80 --address 0.0.0.0
```

Then open:
`http://<internal ip adress of cluster host>:8080/` or, following the example: `http://10.2.4.103:8080/`

Port-forwarding is convenient for local testing, but once you CTRL-C out of the kubectl command, the port will be closed.

## Ingress and edge exposure caveat (read this first)

The Ingress examples in this guide are **k3s-specific** and assume you are using **Traefik** as the Ingress Controller (which is commonly installed by default with k3s, but may be disabled or replaced in some installs).

The examples in this guide use **k3s + Traefik Ingress** because it’s a common, simple lab setup.


In real environments, *how traffic gets to `dsx-connect-api`* is often dictated by the Kubernetes platform (OpenShift Routes,
cloud load balancers, vendor gateways) and/or by external networking/security products. Regarding the
latter, **routing to DSX-Connect could be handled entirely outside the Kubernetes cluster** — for example by a hardware/software load balancer,
WAF (e.g., Barracuda), reverse proxy, or an enterprise ingress gateway. In those designs, you typically **do not use Kubernetes Ingress at all**.
Instead, you expose the API using a Service type that an external device can reach.

### When you do *not* use Ingress

If an external device (WAF/LB/proxy) will route traffic into the cluster, expose `dsx-connect-api` using one of these:

- **NodePort**  
  Use when you have reachable node IPs and want the external device to target `nodeIP:nodePort` directly (common in labs and on-prem clusters without a cloud LB).
- **LoadBalancer**  
  Use when your platform provides a load balancer implementation (cloud provider, MetalLB, etc.) and you want a stable external VIP/DNS.

In both cases, the external device becomes the “ingress” for the application, and Kubernetes Ingress objects are unnecessary.

### When you *do* use Ingress

Note that kubernetes “edge exposure” is not one thing—it varies widely by platform and vendor:

- **Ingress controllers differ** across environments (Traefik, NGINX Ingress, HAProxy, AWS ALB, GCE, Istio gateways, etc.).
- **OpenShift does not use standard Ingress as the primary mechanism**; it typically uses **Routes** (with an OpenShift Router implementation).
- **Load balancers differ** based on where Kubernetes runs (bare metal vs. cloud) and what LB implementation you have (MetalLB, cloud LB integrations, etc.).
- TLS termination, redirects, authentication, WAFs, external-dns, and certificate management can all be handled at different layers depending on your stack.

Because of this, the set of possible combinations of:

- Kubernetes distribution/vendor/version
- Ingress controller (or Routes / Gateway API)
- Load balancer implementation
- DNS and certificate strategy

…is effectively **near endless** and **well beyond the scope** of this deployment guide.

**Scope of this guide:** provide working examples for **k3s + Traefik** that you can use as a reference and adapt to your environment.

If you are on another platform (EKS/AKS/GKE/OpenShift), treat these manifests as **conceptual templates** and use your platform’s recommended ingress/exposure mechanism.


## Ingress example for k3s / Traefik

Use the provided example manifest and edit the host/TLS settings as needed.  Traefik should be installed with k3s by default.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dsx-connect-api
  # replace with the namespace where you installed Traefik
  namespace: dsx-connect
spec:
  # Colima enables a k3s cluster which typically ships with Traefik as the ingress controller.
  # If you installed a different controller, adjust the class accordingly.
  ingressClassName: traefik
  rules:
    # replace with the IP address of your k3s cluster.  for convenience, one can use nip.io to act as DNS, resolving dsx-connect.<ip address>.nip.io to the IP address of your k3s cluster.
    - host: dsx-connect.10.2.4.103.nip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: dsx-connect-api
                port:
                  number: 80

```
Per this example, the `namespace` should be `dsx-connect` (the namespace where you deployed the chart), and the IP address should be `10.2.4.103` (the IP address of the cluster host).

Then apply the ingress:
```bash
kubectl apply -f examples/ingress/ingress-k3s-traefik.yaml
```
Verify that the ingress is deployed:
```bash
kubectl get ingress -n dsx-connect
```
...output should look like this:
```bash
NAME              CLASS     HOSTS                           ADDRESS      PORTS   AGE
dsx-connect-api   traefik   dsx-connect.10.2.4.103.nip.io   10.2.4.103   80      6m36s
```

You should now be able to browse to the DSX-Connect UI at:
```text
http://dsx-connect.10.2.4.103.nip.io
```

## Ingress example for k3s with TLS termination

In this mode, **Traefik terminates TLS** (HTTPS) at the edge, and forwards plain HTTP to the `dsx-connect-api` service inside the cluster.

_Traffic flow_

- Browser/connector → `https://dsx-connect.<IP>.nip.io` (TLS)
- Traefik → `http://dsx-connect-api` (no TLS, inside cluster)

This is a common pattern for labs and many production environments (with a real certificate).

1) Pick your hostname

For a lab VM at `10.2.4.103`, a convenient host is:

- `dsx-connect.10.2.4.103.nip.io`

`nip.io` provides DNS resolution only; you still need ports 80/443 reachable to Traefik.

2) Create a TLS secret in the same namespace as the Ingress

> The TLS Secret must live in the **same namespace as the Ingress resource**.

For a lab/self-signed cert:

```bash
export HOST=dsx-connect.10.2.4.103.nip.io

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout tls-k3s.key -out tls-k3s.crt -days 365 \
  -subj "/CN=$HOST" \
  -addext "subjectAltName=DNS:$HOST"
```

Create the Kubernetes TLS secret (namespace shown as dsx-connect):

```bash
kubectl -n dsx-connect create secret tls tls-k3s \
--cert=tls-k3s.crt \
--key=tls-k3s.key
```
Note that the secret name here is `tls-k3s`.

Verify that the secret was created in our namespace:
```bash
kubectl get secret -n dsx-connect tls-k3s
```

Use a manifest similar to the following, including the tls secret name (see: `examples/ingress/ingress-k3s-traefik-tls.yaml`):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: dsx-connect-api
  namespace: dsx-connect
spec:
  ingressClassName: traefik
  rules:
    - host: dsx-connect.10.2.4.103.nip.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: dsx-connect-api
                port:
                  number: 80
  tls:
    - hosts:
        - dsx-connect.10.2.4.103.nip.io
      secretName: tls-k3s
```

Then apply the ingress (depending on what filename used):
```bash
kubectl apply -f examples/ingress/ingress-k3s-traefik-tls.yaml
```

Verify that the ingress is deployed:
```bash
kubectl get ingress -n dsx-connect
```
...output should look like this:
```bash
kubectl get ingress -n dsx-connect
NAME              CLASS     HOSTS                           ADDRESS      PORTS     AGE
dsx-connect-api   traefik   dsx-connect.10.2.4.103.nip.io   10.2.4.103   80, 443   79m
```

You should now be able to browse to the DSX-Connect UI at:
```text
https://dsx-connect.10.2.4.103.nip.io
```

---
**Enforce HTTP -> HTTPS redirects**

By default, Traefik listens on both:
* web → port 80 (HTTP)
* websecure → port 443 (HTTPS)

Even with TLS configured, users can still access the UI via HTTP.  There's a few ways to enforce HTTPS,
and the simplest is to configure Traefik to redirect HTTP to HTTPS.  Note that this effects ALL traffic going through Traefik,
including the API.

1) Create a HelmChartConfig for Traefik

k3s installs Traefik via a managed Helm chart in the kube-system namespace.
We override its configuration using a HelmChartConfig resource.

Create a file `traefik-https-redirect.yaml`:
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
2) Apply the configuration

```bash 
kubectl apply -f traefik-https-redirect.yaml
```

3) Restart Traefik

```bash
kubectl rollout restart deployment/traefik -n kube-system
```
Wait for Traefik to restart:
```bash
kubectl rollout status deployment/traefik -n kube-system
```
should read `deployment "traefik" successfully rolled out` once complete.

4) Verify Redirect Behavior

```bash
curl -v http://dsx-connect.10.2.4.103.nip.io/ -o /dev/null
```
Expected:

* HTTP/1.1 301 or 308
* Location: https://dsx-connect.10.2.4.103.nip.io/

You can now browse to `http://dsx-connect.10.2.4.103.nip.io` and be redirected to https.

