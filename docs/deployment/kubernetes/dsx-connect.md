# Deploying DSX‑Connect (Helm)

This Helm chart deploys the DSX‑Connect stack (API + workers + Redis +  rsyslog), with an optional in‑cluster DSXA scanner for local testing.

This guide explains the core configuration concepts and details three deployment methods, from a quick local test to a production-grade GitOps workflow.

## Prerequisites

- Kubernetes 1.19+ (a local cluster like Colima or Minikube is recommended for development).
- Helm 3.2+
- `kubectl` configured to point to your cluster.
- `openssl` for generating a self-signed certificate if you plan to enable TLS for development.
- Access to dsx-connect chart release: `oci://registry-1.docker.io/dsxconnect/dsx-connect-chart`   
---
## Concepts

### Release and Namespace Conventions

In the following sections we will use the release name: `dsx` and the  `dsx-connect` namespace.  In examples with name or namespace, the documentation has taken the liberty of inserting these values.  

When using kubectl or helm, use `dsx` as the release name and the `dsx-connect` as the namespace:
```bash
helm upgrade --install dsx <helm root directory> -n dsx-connect -f <helm root directory>/values.yaml <command line arguments>
```
Likewise, in the examples that call for a release name and namespace, this guide has already inserted `dsx` and `dsx-connect` respectively:
```yaml
metadata:
  name: dsx-dsx-connect-api-tls
  namespace: dsx-connect
```

### Chart vs Image Versioning

DSX-Connect helm chart versions are intentionally paired with an appVersion upon release builds.  If you don't specify a chart version when retrieving the chart from OCI, you will always get the _latest_ tagged version

For example, let's assume this is the _latest_ chart in the `dsxconnect` OCI repository:
```yaml
apiVersion: v2
name: dsx-connect-chart
description: A Helm chart for Kubernetes
type: application
version: 0.3.70
appVersion: "0.3.70"
```
This command:
```bash
helm pull oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --untar
```
pulls the latest chart version which in our example is 0.3.70.  Note again that appVersion is also 0.3.70.  You can use `--version x.x.x.` to pull a specific version of the chart. 

Likewise, if you deploy without specifying --version

```bash 
helm upgrade --install dsx -n dsx-connect oci://registry-1.docker.io/dsxconnect/dsx-connect-chart ...
```  
...will pull the _latest_ chart, which in this example is 0.3.70, which means that by default the dsx-connect image used will also be version 0.3.70.  

This a convenience feature meant to simplify test, staging and initial deployments, where starting with the latest version of DSX-Connect is perfectly fine.   

For production deployments, one may want to be more prescriptive, and so, specify the exact version of the chart and/or images used.

Here, specifying the `--version` results in pulling that version of the chart, which in turn is pinned to use that specific version of the DSX-Connect image:
```bash
helm upgrade --install dsx -n dsx-connect \
oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
--version 0.3.67 
``` 
You can also get more specific with which version of the DSX-Connect core image to use, and typically this is how you will
deploy into production environments - overriding the global.image.tag or component image tags with specific versions. This will
address in deployment methods below.

## One-time Bootstrap (per namespace)

Before starting the dsx-connect deployment, create the namespace then create any secrets required by the features you enable.

### Create Namespace

If the namespace `dsx-connect` doesn't already exist, create it: 

```bash
kubectl create namespace dsx-connect
```

### Create required secrets

#### Required secrets by feature

| Feature you enable              | Values toggle                               | Secret required       | Expected default name                        | Required when… |
|---------------------------------|---------------------------------------------|-----------------------|----------------------------------------------|----------------|
| DSX-Connect API auth enrollment | `dsx-connect-api.auth.enabled=true`         | Enrollment token      | `<release>-dsx-connect-api-auth-enrollment`  | You want connectors to authenticate to the DSX-Connect API using an enrollment token |
| TLS                             | `dsx-connect-api.tls.enabled=true`          | TLS certificate       | `<release>-dsx-connect-api-tls`              | You want HTTPS between connectors/clients and the DSX-Connect API |
| DIANNA                          | `dsx-connect-dianna-worker.enabled=true`    | DIANNA API secret     | `dianna-api` (or configured)                 | You are deploying the DIANNA worker to integrate with Deep Instinct management |


#### Create the enrollment token secret 

The helm chart provides an example Secret here: `examples/secrets/auth-enrollment-secret.yaml`, which looks like this:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: <release>-dsx-connect-api-auth-enrollment
  namespace: <namespace>
type: Opaque
stringData:
  ENROLLMENT_TOKEN: "change-me-strong-enrollment-token"
```
We will need to edit this Secret before we can add it into the cluster.
The dsx-connect helm chart is designed to calculate the secret name to look for based on its release name, i.e.: `<release>-dsx-connect-api-auth-enrollment`.  This is a 
common Helm pattern to avoid collisions across namespaces/releases.

The `ENROLLMENT_TOKEN` can be any alphanumeric string, ideally a long random string, such as a UUID.  Complete authentication
enrollment secret for release `dsx` on namespace `dsx-connect`.
 
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dsx-dsx-connect-api-auth-enrollment
  namespace: dsx-connect
type: Opaque
stringData:
  ENROLLMENT_TOKEN: F0DCA5BB-52CB-4944-BB06-64756B27F8A8
```

```bash
kubectl apply -f examples/secrets/auth-enrollment-secret.yaml
```

#### Create the TLS certificate secret

Edit `examples/secrets/tls-secret.yaml` (sample provided with the chart) or create your own. The chart expects a Secret named `<release>-dsx-connect-api-tls` (e.g., `dsx-dsx-connect-api-tls` when the release is `dsx`).

Replace `<base64-encoded-cert>` and `<base64-encoded-key>`.

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

Apply the Secret before deploying the dsx-connect stack:
```bash
kubectl apply -f examples/secrets/tls-secret.yaml
```

#### Create the DIANNA API Secret (if deploying with DIANNA support)
Edit `examples/secrets/dianna-api-secret.yaml` (sample provided) with your DI API token and management URL, then apply it. The sample Secret is named `dianna-api`; set `global.dianna.secretName` (and optionally `dsx-connect-dianna-worker.dianna.secretName`) if you use a different name.

Replace `<DIANNA-API-token>` with the Deep Instinct management console API token (DIANNA User) and the managementURL with your Deep Instinct console.
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: dianna-api
  namespace: dsx-connect
type: Opaque
stringData:
  apiToken: "<DIANNA-API-token>"
  managementUrl: "<your DI console>.deepinstinctweb.com"
```
```bash
kubectl apply -f examples/secrets/dianna-api-secret.yaml
```
## Deploy DSX-Connect (pick one method)

For the full list of values used in deployments, see [Configuration Reference](#configuration-reference).

### Method 1: OCI and Command-Line Overrides (quick/temporary)

Is this guide we will discuss three methods for K8S deployments, the first of which is overriding configuration using command-line overrides.  There are two other approaches in a later section (deployment/kubernetes/advanced-connector-deployment.md)

Here we don't need to pull or edit the chart and values files - we will just use them as-is via referencing the OCI repository where the charts reside and then setting configuration values on the command-line.  

This method is best for quick, temporary deployments, like for local testing. It uses the `--set` or `set-string` flag to provide configuration directly on the command line.

In all examples, we have omitted the `--version` and `global.image.tag` unless otherwise specified.  This will result in using the latest
chart and docker images available in the dsxconnect OCI repository.  Using `--version <x.x.x>` or `--set-string global.image.tag=<x.x.x>` will use specific versions of the chart and/or dsx-connect image (see [Controlling Versioning](#chart-vs-image-versioning)).

In all examples, `<dsxa scanner URL>` is the complete URL: protocol, host<:port>, API path, of the DSXA scanner's scan/binary API path; e.g. `http://somehost:5000/scan/binary/v2`

*   **Deploy DSXA scanner and dsx-connect on the same cluster:**
    Development mode deployment with a local DSXA scanner.  Use the OCI chart, and all settings are just overrides on the command line via --set

    This example assumes env settings for the DSXA appliance URL, token and scanner ID, all of which can be found in the Deep Instinct Management Console.
    ```dotenv
    export DSXA_APPLIANCE_URL=<deep instinct appliance name>.deepinstinctweb.com
    export DSXA_SCANNER_ID=<n>
    export DSXA_TOKEN=<changeme>
    ```
    > these settings above are directly related and passed onto DSXA configurations of the same name

    ```bash 
    helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsxa-scanner.enabled=true \
      --set-string dsxa-scanner.env.APPLIANCE_URL=$DSXA_APPLIANCE_URL \
      --set-string dsxa-scanner.env.TOKEN=$DSXA_TOKEN \
      --set-string dsxa-scanner.env.SCANNER_ID=$DSXA_SCANNER_ID
    ```

  *   **Using an external DSX/A Scanner, HTTP deployment:**
      In this case, using the values.yaml (the default), DSXA scanner is not deployed, so the scan binary URL must be set.
      You can either edit the values.yaml, or copy it and edit, or simply pass in settings on the helm arguments:
      ```bash
      helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsx-connect-api.tls.enabled=true \
      --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL=<dsxa scanner URL>
      ```

*   **For an Authentication-enabled (enrollment) deployment:**

    This is for establishing API authentication between the DSX-Connect core and Connectors.  The enrollment token should be a k8s secret (see above)

    Note also the use of an external DSXA: 
    ```bash
    helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsx-connect-api.auth.enabled=true \ 
      --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL=<dsxa scanner URL>
    ```
    Modify to deploy and use DSXA within the same release/namespace/cluster.


*   **For a TLS-enabled deployment:**

    This is for establishing TLS encryption between the DSX-Connect core and Connectors.  The TLS secret should be a k8s secret (see above).  Note also the use of an external DSXA:

    ```bash
    helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsx-connect-api.tls.enabled=true \
      --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL=<dsxa scanner URL>
    ```
    Add `--set-string dsx-connect-api.tls.secretName=<secret name>` if TLS secret name is something other than `<release>-dsx-connect-api-tls` 


*   **For a DIANNA-enabled deployment:**
    ```bash
    helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsx-connect-dianna-worker.enabled=true \
      --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL=<dsxa scanner URL> 
    ```
    Add `--set-string dsx-connect-dianna-worker.dianna.secretName=<secret name>` if DIANNA secret name is something other than `dianna-api`

*   **Combined TLS + Authentication + DIANNA + external DSXA**
    ```bash
    helm upgrade --install dsx -n dsx-connect \
      oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
      --set dsx-connect-api.tls.enabled=true \
      --set dsx-connect-api.auth.enabled=true \
      --set dsx-connect-dianna-worker.enabled=true \ 
      --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL=<dsxa scanner URL>
    ```



### Method 2: Values file (recommended)

This is the most common and recommended method for managing deployments. 

First, start by pulling the latest dsx-connect helm chart (--untar will unpack the chart):
```
helm pull oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --untar
```
or, if using a specific chart version: 
```
helm pull oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version <x.x.x> --untar
```

The `--untar` flag will unzip the archive downloaded, as a convenience.  After `helm pull --untar`, the chart folder looks like:

```text
dsx-connect-chart/
  Chart.yaml
  values.yaml
  values-dev.yaml
  examples/
    secrets/
      auth-enrollment-secret.yaml
      tls-secret.yaml
      dianna-api-secret.yaml
    ingress/
      ingress-colima.yaml
      ingress-eks-alb.yaml
      openshift-route.yaml
  templates/
    ...
```

Typically one should copy one of the example values files (`values.yaml` or `values-dev.yaml`) and edit the copy.  This makes it easy to return back to defaults,
experiment with types of deployments, and/or pin specific environments and versions of deployments (e.g. `values-staging.yaml`, `values-prod.yaml`, `values-prod-us-west-1.yaml`, `values-prod-0.3.68.yaml`, etc...)

The key difference - `values.yaml` deploys without DSXA, defaults to using API authentication, and has exposed resource tuning parameters typical for staging and production. 
`values-dev.yaml` will deploy a _single_ DSXA scanner on the same cluster, requires no secrets, and is tuned for this simpler set up.

Configure your values.yaml, setting variables as needed (see: [Configuration Reference](#configuration-reference))
Install the chart, referencing your values file with the `-f` flag.  The `.` assumes you are currently in the `dsx-connect-chart/` directory. 

```bash
helm upgrade --install dsx . -f my-dsx-connect-values.yaml -n dsx-connect
```

### Method 3: GitOps (Argo/flux)

This is the definitive, scalable, and secure approach for managing production applications. It uses modern Continuous Delivery (CD) mechanisms.

**The Philosophy:**
Instead of running `helm` commands manually, you declare the desired state of your application in a Git repository. A GitOps tool (like **Argo CD** or **Flux**) runs in your cluster, monitors the repository, and automatically syncs the cluster state to match what is defined in Git.

**The Workflow:**
This involves storing environment-specific values files (e.g., `values-prod.yaml`) in a separate GitOps repository. The GitOps tool then uses these files to automate Helm deployments, providing a fully auditable and declarative system for managing your application lifecycle.

## Post-Deploy

### Verifying the Deployment

After deploying with any method, you can check the status of your release:

```bash
helm list -n dsx-connect
kubectl get pods -n dsx-connect
```

Out should look like this, where Status is 'Running':
```text
NAME                                                    READY   STATUS    RESTARTS        AGE
dsx-dsx-connect-api-6cd95c6c85-htpkj                    1/1     Running   0               2d19h
dsx-dsx-connect-dianna-worker-6c9669f78d-9nkbf          1/1     Running   0               2d19h
dsx-dsx-connect-notification-worker-7c99b48849-gnf8z    1/1     Running   0               2d19h
dsx-dsx-connect-results-worker-bd79b9d68-jsrvn          1/1     Running   0               2d19h
dsx-dsx-connect-scan-request-worker-854bb6bdf4-7j9fw    1/1     Running   0               2d19h
dsx-dsx-connect-verdict-action-worker-bb8d87f7d-zjgxb   1/1     Running   0               2d19h
dsx-dsxa-scanner-786f89f587-qdcg5                       1/1     Running   0               2d21h
redis-7f9d966b5f-km7kx                                  1/1     Running   75 (105m ago)   2d19h
rsyslog-5475d977cb-9nj2b                                1/1     Running   2 (11h ago)     2d19h
```

### Access (port-forward/ingress)

For the following examples, we will assume the kubernetes cluster is installed on a host `10.2.4.103`.   Substitute your own IP address as needed.

#### Port-forward for quick access

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

#### Ingress and edge exposure caveat (read this first)

The Ingress examples in this guide are **k3s-specific** and assume you are using **Traefik** as the Ingress Controller (which is commonly installed by default with k3s, but may be disabled or replaced in some installs).

The examples in this guide use **k3s + Traefik Ingress** because it’s a common, simple lab setup. 


In real environments, *how traffic gets to `dsx-connect-api`* is often dictated by the Kubernetes platform (OpenShift Routes, 
cloud load balancers, vendor gateways) and/or by external networking/security products. Regarding the 
latter, **routing to DSX-Connect could be handled entirely outside the Kubernetes cluster** — for example by a hardware/software load balancer, 
WAF (e.g., Barracuda), reverse proxy, or an enterprise ingress gateway. In those designs, you typically **do not use Kubernetes Ingress at all**. 
Instead, you expose the API using a Service type that an external device can reach.

When you do *not* use Ingress

If an external device (WAF/LB/proxy) will route traffic into the cluster, expose `dsx-connect-api` using one of these:

- **NodePort**  
  Use when you have reachable node IPs and want the external device to target `nodeIP:nodePort` directly (common in labs and on-prem clusters without a cloud LB).
- **LoadBalancer**  
  Use when your platform provides a load balancer implementation (cloud provider, MetalLB, etc.) and you want a stable external VIP/DNS.

In both cases, the external device becomes the “ingress” for the application, and Kubernetes Ingress objects are unnecessary.

When you *do* use Ingress, just note that kubernetes “edge exposure” is not one thing—it varies widely by platform and vendor:

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


#### Ingress example for k3s / Traefik

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

#### Ingress example for k3s with TLS termination

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

## Deployment Done - In the DSX-Connect Console and Next Steps

With everything deployed successfully and one the access methods applied (see [Access](#access-port-forwardingress)) you
should see a UI similar to this:

![UI Screenshot no connectors](../../assets/ui_screenshot_no_connectors.png)

You should see the message: "Connected..." in the top left - this indicates that the DSX-Connect components can reach DSXA (and thus, scanning is ready).

Also, note that there's not a lot you can _do_ yet, other than looking at current configuration (the gear icon), since you haven't scanned anything yet.
To do so, you will need to add a connector.

## Operations / Advanced

Many deployment variables have sensible default values set directly within the component templates.  You only need to override them if your deployment requires a different value.

To override a default environment variable, specify it under the `env` section of the respective component in your custom `values.yaml` file.

### Syslog forwarding

The `dsx-connect-results-worker` component is responsible for logging scan results to syslog.

This helm chart default includes a rsyslog service that can be used to collect scan results within the cluster.  The rsyslog 
service is enabled by default, but can be disabled by setting `rsyslog.enabled=false` in the `values.yaml` file.

#### Syslog format

Syslog payloads are JSON objects with these top-level fields:

- `timestamp`: UTC ISO-8601 timestamp.
- `source`: constant `dsx-connect`.
- `scan_request`: the original scan request (location, metainfo, connector, scan_job_id, size_in_bytes).
- `verdict`: DSXA verdict details (verdict, file_info, verdict_details, scan_duration_in_microseconds, etc.).
- `item_action`: connector action status (status, message, item_action).

Example payload:

```json
{
  "timestamp": "2026-02-10T23:12:34.567Z",
  "source": "dsx-connect",
  "scan_request": {
    "location": "/path/to/file.docx",
    "metainfo": "{\"bucket\":\"docs\"}",
    "connector_url": "http://filesystem-connector:8080",
    "size_in_bytes": 14844,
    "scan_job_id": "job-123"
  },
  "verdict": {
    "scan_guid": "007ea79292ae4261ad82269cd13051b9",
    "verdict": "Benign",
    "verdict_details": { "event_description": "File identified as benign" },
    "file_info": {
      "file_type": "OOXMLFileType",
      "file_size_in_bytes": 14844,
      "file_hash": "286865e7337f30ac2d119d8edc9c36f6a11552eb23c50a1137a19e0ace921e8e"
    },
    "scan_duration_in_microseconds": 10404
  },
  "item_action": {
    "status": "nothing",
    "message": "No action taken",
    "item_action": "nothing"
  }
}
```

On the wire, syslog lines are prefixed with `dsx-connect ` followed by the JSON payload. The bundled rsyslog chart extracts the JSON for output/forwarding.

#### Reading syslog output

By default, the bundled rsyslog writes parsed scan-result JSON to stdout. That means you can observe syslog output by tailing the rsyslog pod logs, for example:

`kubectl logs -n <namespace> -l app.kubernetes.io/name=rsyslog -f`

This is the quickest way to verify scan-result messages are flowing before forwarding to an external collector.

#### Forward internal rsyslog to an external syslog

The bundled rsyslog chart supports forwarding all scan-result messages to an external syslog receiver. Enable forwarding under `rsyslog.config.forward`:

```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "syslog.example.com"
      port: 514
      tls: false
```

#### Forward to Papertrail

Papertrail accepts standard syslog over TCP or TLS. Use the hostname/port from your Papertrail log destination.

TCP (no TLS):
```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "logsN.papertrailapp.com"
      port: 514
      tls: false
```

TLS (recommended by Papertrail):
```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "logsN.papertrailapp.com"
      port: 6514
      tls: true
      permittedPeer: "*.papertrailapp.com"
```

TLS forwarding requires an rsyslog image with the `gtls` module. See the Developer's Guide: [Rsyslog TLS Image](../../operations/rsyslog-tls-image.md).

Notes:

- Replace `logsN.papertrailapp.com` with your Papertrail destination hostname.
- If you enable TLS, ensure `permittedPeer` matches the certificate name used by your destination.

#### Forward to SolarWinds Observability (token-based syslog)

SolarWinds Observability uses a token-based syslog format. Set `format` to `solarwinds` and provide the destination token.

```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "syslog.collector.na-01.cloud.solarwinds.com"
      port: 6514
      tls: true
      permittedPeer: "*.collector.na-01.cloud.solarwinds.com"
      format: "solarwinds"
      token: "<your-syslog-token>"
```


### Concurrency and Replicas

Workers scale with two knobs. Use them together for best results:

- Replica count (`replicaCount`): number of pods. Each pod has its own CPU/memory limits/requests and its own Celery process. Good for horizontal scaling and resilience.
- Concurrency (`celery.concurrency`): number of task workers inside one pod. Increases parallelism within a pod; shares that pod’s resources.

Guidance:

- The scan request workers are generally the place to start with concurrency. These workers take enqueued scan requests, read a file from a connector, and send it to DSXA for scanning.
- Default scan_request concurrency is `2`, so each scan_request pod can handle two scan requests at a time. Adding another pod doubles that (e.g., 2 pods × 2 concurrency = 4 total workers).
- Start by raising `celery.concurrency` modestly (2–4), then add `replicaCount` to spread load across nodes.
- If CPU-bound within a pod, increase pod resources or add replicas. If I/O-bound (network/Redis/HTTP), modest concurrency increases often help.
- Scale downstream workers (verdict/result/notification) when increasing request throughput to avoid bottlenecks.

#### Practical Tuning Tips
- Continue favoring modest Celery concurrency (2–4) before adding pods; add replicas when you see CPU saturation or want resiliency.
- For connectors, bump `workers` to 2–4 if read_file handlers are CPU-bound or you want more in-pod parallel reads; add connector replicas if a single pod’s CPU or network is saturated, or for HA.
- If you notice uneven distribution across connector replicas due to HTTP keep-alive, higher Celery concurrency tends to open more connections and spread load better; you can also tune httpx connection limits if needed later.

#### Note on Connector Replicas

Connectors also have a replicaCount, but it's important to understand what it's doing:

- Setting a connector chart’s `replicaCount > 1` deploys multiple identical connector pods that each register independently with dsx-connect, each with a unique connector UUID. The UI will show multiple connectors for the same asset/filter.
- A Full Scan request (from the UI or API) targets a single registered connector instance. Increasing `replicaCount` does not parallelize a single full-scan enqueue path.
- Where replicas do help:
    - High availability (one pod can restart while another continues to serve), and
    - Serving concurrent `read_file` requests from the dsx-connect scan-request workers (Kubernetes Service balances connections across pods; higher Celery concurrency opens more connections and spreads load).
      To parallelize work across a single asset intentionally, prefer:
    - Increasing connector `workers` (Uvicorn processes) for in-pod concurrency, and/or
    - Running multiple connector releases with different `DSXCONNECTOR_FILTER` partitions (sharding), so Full Scan is performed in parallel across slices by distinct connector instances.



### Client Trust and CA Bundles

When clients (like the Azure Blob Storage Connector) communicate with the `dsx-connect-api` server over HTTPS, they must be able to verify the server's identity. If the `dsx-connect-api` server is using a certificate from an internal or self-signed Certificate Authority (CA), you must provide that CA's certificate to each client in a **CA Bundle**.

**Encryption vs. Authentication:**
It is important to understand that even with `verify=false`, the connection is still **encrypted**. However, without verification, the identity of the server is not **authenticated**. This leaves you vulnerable to man-in-the-middle attacks. **Using a CA bundle to verify the connection is critical for security.**

**Procedure for Clients (e.g., Azure Blob Storage Connector):**

1.  **Obtain the CA Certificate:** Get the public certificate file (e.g., `ca.crt`) of the CA that signed your `dsx-connect-api` server's certificate.

2.  **Create a Secret from the CA Certificate:**
    ```bash
    kubectl create secret generic dsx-connect-ca --from-file=ca.crt=/path/to/your/ca.crt
    ```

3.  **Configure the Client's Helm Chart:**
    Refer to the client's (e.g., `connectors/azure_blob_storage/deploy/helm/DEVELOPER_README.md`) documentation for how to configure its `DSXCONNECTOR_CA_BUNDLE` and `DSXCONNECTOR_VERIFY_TLS` settings to trust this CA.



## Ingress & Load Balancer Examples

The core chart deliberately stops at ClusterIP services so it works across any platform. If you need ingress routes or load balancer services, use the sample manifests under `dsx_connect/deploy/helm/examples/ingress/`.

- Pick the file that matches your environment (e.g., `ingress-colima.yaml`, `ingress-eks-alb.yaml`, `openshift-route.yaml`)
- Edit hosts/TLS secrets as needed
- Apply it after installing the chart:

```bash
kubectl apply -f dsx_connect/deploy/helm/examples/ingress/ingress-colima.yaml
```

These are meant as starting points—feel free to adapt or author your own ingress resources if your environment requires different settings.

## Configuration Reference

The following section highlights some of the most common configurations for deployments.  These
will be used in the next sections when we deploy DSX-Connect.

Note that the `values.yaml` contains many more configuration option, many of which will not be detailed here as they are common
helm/k8s deployment settings, e.g., `resources.requests.cpu/memory`.

### Global settings
The `global` section covers common settings used by one or more deployed components:

| Name                                              | Description                                                        | Example Value                                          | Common Use                                       
  |---------------------------------------------------|--------------------------------------------------------------------|--------------------------------------------------------|--------------------------------------------------|
| `global.image.tag`                                | dsx-connect image tag to deploy; if blank, uses Chart `appVersion` | `0.3.69`                                               | Leave blank `''` and use latest version          |                                    |
| `global.image.repository`                         | Docker Hub reposiroty hosting DSX-Connect images                   | Defaults to dsxconnect/dsx-connect                     | Leave as-is unless you use a specific repository | 
| `global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL`  | DSXA scan endpoint (use when DSXA is external to this chart)       | `https://my-dsxa.example.com/scan/binary/v2`           | << that                                          |                                                | 
| `global.env.DSXCONNECT_SCANNER__AUTH_TOKEN`       | DSXA scanner API authorization token                               | Needed if DSXA scanner deployed with API authorization | Leave commented out if authorization not used    |  


Next, each of the deployed services:
### dsxa-scanner

| Name                    | Description                                                                                                                                                                          | Example Value                                                          | Common Use                              |
|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|-----------------------------------------|
| `dsxa-scanner.enabled`  | if `false`, DSX-Connect uses scanner specified by DSXCONNECT_SCANNER__SCAN_BINARY_URL`; if `true` a local DSXA scanner will be deployed and used                                     | `false` or `true`                                                      | `false`                                 |
| `dsxa-scanner.env.xxxx` | If enabled, uncomment and supply DSXA scanner settings, as defined in the DSX for Applications Deployment Guide.  NOTE: if not using AUTH_TOKEN, this line needs to be commented out | ```APPLIANCE_URL: "https://your-dsxa-appliance.deepinstinctweb.com" ``` | Leave commented out if enabled = `false` |

### dsx-connect-api

| Name                                  | Description                                                                                                    | Example Value                                         | Common Use                                                                                                |
|---------------------------------------|----------------------------------------------------------------------------------------------------------------|-------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `dsx-connect-api.auth.enabled`        | if `true`, DSX-Connect API expects an Enrollment token for bootstrapping Connector <-> core API authentication | `true` or `false`                                     | `true`                                                                                                    |
| `dsx-connect-api.auth.enrollment.key` | Secret key name used to read the enrollment token                                                              | `ENROLLMENT_TOKEN`                                    | Leave as default unless your Secret uses a different key                                                  |
| `dsx-connect-api.tls.enabled` | if `true`, DSX-Connect API expects a TLS secret                                                                | `true` or `false`                                     |                                                                                                           |
| `dsx-connect-api.tls.secretName` | Used when tls enabled, references the TLS secret | `<release>-dsx-connect-api-tls` or line commented out | Defaults to `<release>-dsx-connect-api-tls`.  If secret applied with this name, leave this line commented |                              

### dsx-connect-scan-request-worker

| Name                                               | Description                                   | Example Value    | Common Use |
|----------------------------------------------------|-----------------------------------------------|------------------|------------|
| `dsx-connect-scan-request-worker.enabled`          | Enable the scan request worker deployment     | `true` or `false`| `true`     |
| `dsx-connect-scan-request-worker.replicaCount`     | Number of worker pods                         | `1`              | `1`        |
| `dsx-connect-scan-request-worker.env.LOG_LEVEL`    | Log level for the worker                      | `debug`, `info`, `warning`, `error` | `info`     |
| `dsx-connect-scan-request-worker.celery.concurrency` | Number of worker processes per pod          | `2`              | `2`        |

### dsx-connect-verdict-action-worker

| Name                                                | Description                                   | Example Value    | Common Use |
|-----------------------------------------------------|-----------------------------------------------|------------------|------------|
| `dsx-connect-verdict-action-worker.enabled`         | Enable the verdict action worker deployment   | `true` or `false`| `true`     |
| `dsx-connect-verdict-action-worker.replicaCount`    | Number of worker pods                         | `1`              | `1`        |
| `dsx-connect-verdict-action-worker.env.LOG_LEVEL`   | Log level for the worker                      | `debug`, `info`, `warning`, `error` | `info`     |
| `dsx-connect-verdict-action-worker.celery.concurrency` | Number of worker processes per pod         | `1`              | `1`        |

### dsx-connect-results-worker

| Name                                            | Description                                   | Example Value    | Common Use |
|-------------------------------------------------|-----------------------------------------------|------------------|------------|
| `dsx-connect-results-worker.enabled`            | Enable the results worker deployment          | `true` or `false`| `true`     |
| `dsx-connect-results-worker.replicaCount`       | Number of worker pods                         | `1`              | `1`        |
| `dsx-connect-results-worker.env.LOG_LEVEL`      | Log level for the worker                      | `debug`, `info`, `warning`, `error` | `info`     |
| `dsx-connect-results-worker.celery.concurrency` | Number of worker processes per pod            | `1`              | `1`        |

### dsx-connect-notification-worker

| Name                                                  | Description                                   | Example Value    | Common Use |
|-------------------------------------------------------|-----------------------------------------------|------------------|------------|
| `dsx-connect-notification-worker.enabled`             | Enable the notification worker deployment     | `true` or `false`| `true`     |
| `dsx-connect-notification-worker.replicaCount`        | Number of worker pods                         | `1`              | `1`        |
| `dsx-connect-notification-worker.env.LOG_LEVEL`       | Log level for the worker                      | `debug`, `info`, `warning`, `error` | `info`     |
| `dsx-connect-notification-worker.celery.concurrency`  | Number of worker processes per pod            | `1`              | `1`        |

### dsx-connect-dianna-worker

| Name                                           | Description                                   | Example Value    | Common Use |
|------------------------------------------------|-----------------------------------------------|------------------|------------|
| `dsx-connect-dianna-worker.enabled`            | Enable the DIANNA worker deployment           | `false` or `true`| `false`    |
| `dsx-connect-dianna-worker.replicaCount`       | Number of worker pods                         | `1`              | `1`        |
| `dsx-connect-dianna-worker.env.LOG_LEVEL`      | Log level for the worker                      | `debug`, `info`, `warning`, `error` | `info`     |
| `dsx-connect-dianna-worker.celery.concurrency` | Number of worker processes per pod            | `1`              | `1`        |


