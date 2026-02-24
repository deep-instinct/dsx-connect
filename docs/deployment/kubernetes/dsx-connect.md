# Deploying DSX‑Connect (Helm)

This Helm chart deploys the DSX‑Connect stack (API + workers + Redis +  rsyslog), with an optional in‑cluster DSXA scanner for local testing.

This guide explains the core configuration concepts and details three deployment methods, from a quick local test to a production-grade GitOps workflow.

## Prerequisites

- Kubernetes 1.19+ (a local cluster like Colima or Minikube is recommended for development).
- Helm 3.2+
- `kubectl` configured to point to your cluster.
- `openssl` for generating a self-signed certificate if you plan to enable TLS for development.
- Access to dsx-connect chart release: `oci://registry-1.docker.io/dsxconnect/dsx-connect-chart`   


## Naming Conventions

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

## Chart vs Image Versioning

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

Before deploying DSX-Connect, create the namespace and any secrets required by the features you enable.

### Create namespace

If the namespace `dsx-connect` doesn't already exist:

```bash
kubectl create namespace dsx-connect
```

### Create required secrets

#### Required secrets by feature

| Feature you enable                                         | Values toggle                            | Secret required   | Expected default name                       | Required when…                                                                       |
| ---------------------------------------------------------- | ---------------------------------------- | ----------------- | ------------------------------------------- | ------------------------------------------------------------------------------------ |
| [Enrollment token (API auth bootstrap)](authentication.md) | `dsx-connect-api.auth.enabled=true`      | Enrollment token  | `<release>-dsx-connect-api-auth-enrollment` | You want connectors to authenticate to the DSX-Connect API using an enrollment token |
| [TLS](tls.md)                                              | `dsx-connect-api.tls.enabled=true`       | TLS certificate   | `<release>-dsx-connect-api-tls`             | You want HTTPS between connectors/clients and the DSX-Connect API                    |
| [DIANNA](dianna.md)                                        | `dsx-connect-dianna-worker.enabled=true` | DIANNA API secret | `dianna-api` (or configured)                | You are deploying the DIANNA worker to integrate with Deep Instinct management       |


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
## Deployment Done - In the DSX-Connect Console

With everything deployed successfully and one the access methods applied (see [Access](#access-port-forwardingress)) you
should see a UI similar to this:

![UI Screenshot no connectors](../../assets/ui_screenshot_no_connectors.png)

You should see the message: "Connected..." in the top left - this indicates that the DSX-Connect components can reach DSXA (and thus, scanning is ready).

Also, note that there's not a lot you can _do_ yet, other than looking at current configuration (the gear icon), since you haven't scanned anything yet.
To do so, you will need to add a connector.

## Next Steps / Links

Advanced Deployment Guides:

- [Access and Ingress](access.md)
- [Authentication](authentication.md)
- [TLS](tls.md)
- [DIANNA](dianna.md)

- [Connectors]

Operations:

- For performance tuning guidance, see:
- [Performance Tuning with Job Comparisons](../../operations/performance-tuning-job-comparisons.md)
- [Syslog Format and Forwarding](../../operations/syslog.md)
- [Upgrading](upgrading.md)
- [Uninstalling](uninstalling.md)
- [Troubleshooting](troubleshooting.md)

