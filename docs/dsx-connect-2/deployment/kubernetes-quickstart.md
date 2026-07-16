# DSX-Connect 2 Kubernetes Helm Quickstart

This quickstart deploys:

* DSX-Connect 2 control plane
* PostgreSQL and RabbitMQ for local state and job dispatch
* DSX-Connect 2 workers
* Optional single DSXA scanner instance
* The Filesystem connector

The example uses released OCI Helm charts and a DSXA scanner. It is intended for local k3s, Colima, or lab Kubernetes validation.

By the end, you will:

* Access the DSX-Connect Operator Console
* See the Filesystem connector registered
* Enable protection for a filesystem asset
* Run a scan and see results

## Prerequisites

* Kubernetes 1.19+
* Helm 3+
* kubectl configured for your cluster
* A node-local path that can be mounted with `hostPath`
* A reachable DSXA scanner, or DSXA registration values for the optional scanner step
* Traefik available as the cluster ingress controller for the ingress path

For local Kubernetes guidance, see [Lightweight K8S Recommendations](../../reference/installations/kubernetes.md). For k3s / Traefik ingress details, see [Reference > Traefik](../../reference/traefik.md).

## 1) Set Variables

!!! note
    Helm chart `--version` expects a chart version such as `2.0.3`.
    To install the latest chart, omit the `--version` argument instead of setting it to `latest`.

```bash
export NAMESPACE=dsx-connect
export RELEASE=dsx-connect
export DSX_CONNECT_VERSION=2.0.11
export FILESYSTEM_CONNECTOR_VERSION=2.0.6
export CLUSTER_HOST_IP=10.2.4.103
export DSX_CONNECT_HOST="dsx-connect.${CLUSTER_HOST_IP}.nip.io"
```

Set `CLUSTER_HOST_IP` to the IP address where Traefik is reachable. For k3s and Colima labs, this is usually the host or VM IP that exposes ports `80` and `443`.

Create the namespace:

```bash
kubectl create namespace $NAMESPACE
```

## 2) Deploy a DSXA Scanner (Optional)

If you have a DSXA scanner deployed already and want to use it, skip this step and set:

```bash
export DSXA_SCANNER_BASE_URL="http://<dsxa-host>:15000"
```

Use an address that is reachable from inside the Kubernetes cluster, not only from your laptop.

Otherwise, take this step to deploy a single DSXA scanner instance.

Set DSXA registration values:

```bash
export DSXA_IMAGE="dsxconnect/dpa-rocky9:4.2.0.2176"
export DSXA_APPLIANCE_URL="<your-appliance>.deepinstinctweb.com"
export DSXA_TOKEN="<scanner-registration-token>"
export DSXA_SCANNER_ID="<scanner-id>"
export DSXA_SCANNER_BASE_URL="http://dsxa-scanner:15000"
```

Create the DSXA Secret:

```bash
kubectl create secret generic dsxa-scanner-env \
  --namespace "$NAMESPACE" \
  --from-literal=APPLIANCE_URL="$DSXA_APPLIANCE_URL" \
  --from-literal=TOKEN="$DSXA_TOKEN" \
  --from-literal=SCANNER_ID="$DSXA_SCANNER_ID" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Deploy one DSXA scanner pod and an internal service:

```bash
cat > /tmp/dsxa-scanner.yaml <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dsxa-scanner
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: dsxa-scanner
  template:
    metadata:
      labels:
        app.kubernetes.io/name: dsxa-scanner
    spec:
      containers:
        - name: dsxa-scanner
          image: ${DSXA_IMAGE}
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 5000
          envFrom:
            - secretRef:
                name: dsxa-scanner-env
          env:
            - name: FLAVOR
              value: "rest,config"
            - name: NO_SSL
              value: "true"
---
apiVersion: v1
kind: Service
metadata:
  name: dsxa-scanner
  namespace: ${NAMESPACE}
spec:
  selector:
    app.kubernetes.io/name: dsxa-scanner
  ports:
    - name: http
      port: 15000
      targetPort: 5000
EOF

kubectl apply -f /tmp/dsxa-scanner.yaml
```

Wait for the scanner to start:

```bash
kubectl rollout status deployment/dsxa-scanner -n "$NAMESPACE" --timeout=5m
kubectl logs -n "$NAMESPACE" deploy/dsxa-scanner --tail=80
```

Look for registration and classifier initialization messages before running scans.

## 3) Create DSX-Connect 2 Values

Create a local values file for the full stack:

```bash
cat > /tmp/dsx-connect-2-values.yaml <<EOF
image:
  pullPolicy: "Always"

env:
  DSX_CONNECT_NG__ENVIRONMENT: "dev"
  DSX_CONNECT_NG__CONTROL_PLANE_BACKEND: "postgres"
  DSX_CONNECT_NG__JOB_BUS_BACKEND: "rabbitmq"
  DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA: "true"
  DSX_CONNECT_NG_POSTGRES__URL: "postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2"
  DSX_CONNECT_NG_RABBITMQ__URL: "amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F"
  DSX_CONNECT_NG_SCANNER__MODE: "dsxa"
  DSX_CONNECT_NG_SCANNER__BASE_URL: "${DSXA_SCANNER_BASE_URL}"
  DSX_CONNECT_NG_READERS__DEFAULT_STRATEGY: "native"

postgresql:
  enabled: true
  persistence:
    enabled: false

rabbitmq:
  enabled: true
  persistence:
    enabled: false

workers:
  relay:
    enabled: true
  scan:
    enabled: true
    args: ["--prefetch-count", "10"]
  policy:
    enabled: true
    args: ["--prefetch-count", "100"]
  remediation:
    enabled: true
  resultSink:
    enabled: true
  dianna:
    enabled: false

ingress:
  enabled: true
  className: traefik
  hosts:
    - host: "${DSX_CONNECT_HOST}"
      paths:
        - path: /
          pathType: Prefix
EOF
```

This values file keeps PostgreSQL and RabbitMQ non-persistent for quick local testing and creates a Traefik `Ingress` for the Operator Console. If your cluster does not use Traefik, set `ingress.enabled: false` and use the port-forward option in step 7.

## 4) Install DSX-Connect 2

```bash
helm upgrade --install $RELEASE \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version $DSX_CONNECT_VERSION \
  --namespace $NAMESPACE \
  -f /tmp/dsx-connect-2-values.yaml
```

Check pods:

```bash
kubectl get pods -n $NAMESPACE
```

Expected pods include:

* `dsx-connect-api`
* `dsx-connect-postgres`
* `dsx-connect-rabbitmq`
* `dsx-connect-relay`
* `dsx-connect-scan`
* `dsx-connect-policy`
* `dsx-connect-remediation`
* `dsx-connect-result-sink`
* `dsx-connect-dianna`

## 5) Create Test Files

Choose one option based on your local cluster.

### Option A: Colima

Use a path inside the Colima VM:

```bash
export HOST_SCAN_PATH=/var/dsx-connect-2-test
colima ssh -- sudo mkdir -p "$HOST_SCAN_PATH"
colima ssh -- sh -lc 'echo "hello dsx connect 2" | sudo tee /var/dsx-connect-2-test/test.txt >/dev/null'
```

If you want to scan a macOS path, start Colima with that path mounted:

```bash
colima stop
colima start --mount /Users/<you>:/Users/<you>
```

Then set `HOST_SCAN_PATH` to the mounted macOS path.

### Option B: k3s

Use a path on the k3s node host filesystem:

```bash
export HOST_SCAN_PATH=/var/dsx-connect-2-test
sudo mkdir -p "$HOST_SCAN_PATH"
echo "hello dsx connect 2" | sudo tee "$HOST_SCAN_PATH/test.txt" >/dev/null
```

## 6) Install the Filesystem Connector

Create a values file for DSX-Connect 2 registration:

```bash
cat > /tmp/filesystem-connector-2-values.yaml <<EOF
env:
  LOG_LEVEL: "debug"
  DSXCONNECTOR_APP_ENV: "dev"
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "filesystem-local-1"
  DSXCONNECTOR_NG_PLATFORM: "filesystem"
  DSXCONNECTOR_NG_PLATFORM_KEY: "local-kubernetes"
  DSXCONNECTOR_ASSET: "/app/scan_folder"
  DSXCONNECTOR_ITEM_ACTION: "nothing"
  DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "/app/quarantine"
  DSXCONNECTOR_DATA_DIR: "/app/data"
  DSXCONNECTOR_MONITOR: "false"
  DSXCONNECTOR_SCAN_BY_PATH: "False"

scanVolume:
  enabled: true
  mountPath: "/app/scan_folder"
  hostPath: "$HOST_SCAN_PATH"

dataVolume:
  enabled: true
  mountPath: "/app/data"
EOF
```

This mounts the k3s node path `$HOST_SCAN_PATH` into the connector pod at `/app/scan_folder`.
Keep `DSXCONNECTOR_ASSET` set to `/app/scan_folder`; do not set it to the host path or PVC name.

In **Assets > Protected**, `configured_asset` shows the mounted root.
`inventory_enumeration` shows first-level folders under that root, which are the usual protection candidates.
Files directly under the root are scan objects, not assets.

Install the connector:

```bash
helm upgrade --install fs \
  oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
  --version $FILESYSTEM_CONNECTOR_VERSION \
  --namespace $NAMESPACE \
  -f /tmp/filesystem-connector-2-values.yaml
```

Check connector logs:

```bash
kubectl logs -n $NAMESPACE deploy/fs-filesystem-connector -f
```

Look for connector registration messages, then check pod readiness:

```bash
kubectl get pods -n $NAMESPACE
```

## 7) Access the Operator Console

### Option A: Traefik Ingress

For k3s and Colima labs, Traefik gives you a stable browser URL without keeping a `kubectl port-forward` process open. This is the recommended quickstart path when Traefik is available.

For information on installing, checking, and configuring Traefik, see [Reference > Traefik](../../reference/traefik.md).

Verify that the chart created the ingress:

```bash
kubectl get ingress -n "$NAMESPACE"
kubectl describe ingress -n "$NAMESPACE" dsx-connect-api
```

Open:

```text
http://dsx-connect.10.2.4.103.nip.io/
```

If you changed `CLUSTER_HOST_IP`, use:

```bash
echo "http://${DSX_CONNECT_HOST}/"
```

For TLS termination or HTTP-to-HTTPS redirects with Traefik, see [Reference > Traefik](../../reference/traefik.md).

### Option B: Port-Forward Fallback

Use port-forwarding when Traefik is not installed or when the cluster host ports are not reachable from your browser:

```bash
kubectl port-forward -n $NAMESPACE svc/dsx-connect-api 8091:8091
```

Open:

```text
http://127.0.0.1:8091/
```

You should see:

* DSXA scanner status in the top row
* Filesystem connector under **Assets > Connectors**
* The filesystem asset under **Assets > Protected**

## 8) Enable Protection and Run a Scan

In the Operator Console:

1. Go to **Assets > Protected**.
2. Select the Filesystem connector.
3. Find the filesystem asset.
4. Enable protection with the default protection profile.
5. Click **Scan**.
6. Open **Scan Results** and monitor progress.

This quickstart uses DSXA scanner mode, so scan results come from the configured DSXA scanner.
For control-plane-only smoke tests without DSXA, set `DSX_CONNECT_NG_SCANNER__MODE` back to `"stub"` in `/tmp/dsx-connect-2-values.yaml`.

If scan work exhausts retries and lands in a dead letter queue, see [Dead Letter Queues](../operations/dead-letter-queues.md) for the current RabbitMQ inspection and scan restart flow.

## Cleanup

```bash
helm uninstall fs -n $NAMESPACE
kubectl delete deployment dsxa-scanner -n $NAMESPACE 2>/dev/null || true
kubectl delete service dsxa-scanner -n $NAMESPACE 2>/dev/null || true
kubectl delete secret dsxa-scanner-env -n $NAMESPACE 2>/dev/null || true
helm uninstall $RELEASE -n $NAMESPACE
kubectl delete namespace $NAMESPACE
```

## Next Steps

* [Deploy DSX-Connect 2 with Helm](kubernetes.md)
* [Deploy Connectors for DSX-Connect 2](connectors/index.md)
* [Packaging Releases](../packaging-releases.md)
