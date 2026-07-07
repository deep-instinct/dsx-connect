# DSX-Connect 2 Kubernetes Helm Quickstart

This quickstart deploys:

* DSX-Connect 2 control plane
* PostgreSQL and RabbitMQ for local state and job dispatch
* DSX-Connect 2 workers
* The Filesystem connector

The example uses released OCI Helm charts and a stub scanner. It is intended for local k3s, Colima, or lab Kubernetes validation.

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

For local Kubernetes guidance, see [Lightweight K8S Recommendations](../../reference/installations/kubernetes.md).

## 1) Set Variables

```bash
export NAMESPACE=dsx-connect
export RELEASE=dsx-connect
export DSX_CONNECT_VERSION=2.0.1
export CONNECTOR_VERSION=2.0.2
```

Create the namespace:

```bash
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
```

## 2) Create DSX-Connect 2 Values

Create a local values file for the full stack:

```bash
cat > /tmp/dsx-connect-2-values.yaml <<'EOF'
env:
  DSX_CONNECT_NG__ENVIRONMENT: "dev"
  DSX_CONNECT_NG__CONTROL_PLANE_BACKEND: "postgres"
  DSX_CONNECT_NG__JOB_BUS_BACKEND: "rabbitmq"
  DSX_CONNECT_NG_POSTGRES__AUTO_APPLY_SCHEMA: "true"
  DSX_CONNECT_NG_POSTGRES__URL: "postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2"
  DSX_CONNECT_NG_RABBITMQ__URL: "amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F"
  DSX_CONNECT_NG_SCANNER__MODE: "stub"
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
  remediation:
    enabled: true
  resultSink:
    enabled: true
  dianna:
    enabled: true
EOF
```

This values file keeps PostgreSQL and RabbitMQ non-persistent for quick local testing.

## 3) Install DSX-Connect 2

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

## 4) Create Test Files

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

## 5) Install the Filesystem Connector

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

Install the connector:

```bash
helm upgrade --install fs \
  oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
  --version $CONNECTOR_VERSION \
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

## 6) Access the Operator Console

Port-forward the API service:

```bash
kubectl port-forward -n $NAMESPACE svc/dsx-connect-api 8091:8091
```

Open:

```text
http://127.0.0.1:8091/api/v1/ui/
```

You should see:

* DSXA scanner status in the top row
* Filesystem connector under **Assets > Connectors**
* The filesystem asset under **Assets > Protected**

## 7) Enable Protection and Run a Scan

In the Operator Console:

1. Go to **Assets > Protected**.
2. Select the Filesystem connector.
3. Find the filesystem asset.
4. Enable protection with the default protection profile.
5. Click **Scan**.
6. Open **Scan Results** and monitor progress.

Because this quickstart uses the stub scanner, the scan path validates the control-plane, connector, queue, worker, and result flow without requiring DSXA credentials.

## Use a Real DSXA Scanner

To use a reachable DSXA scanner instead of the stub scanner, set these values on the DSX-Connect 2 chart:

```yaml
env:
  DSX_CONNECT_NG_SCANNER__MODE: "dsxa"
  DSX_CONNECT_NG_SCANNER__BASE_URL: "http://<dsxa-host>:15000"
```

Then upgrade the control plane:

```bash
helm upgrade --install $RELEASE \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version $VERSION \
  --namespace $NAMESPACE \
  -f /tmp/dsx-connect-2-values.yaml \
  --set env.DSX_CONNECT_NG_SCANNER__MODE=dsxa \
  --set env.DSX_CONNECT_NG_SCANNER__BASE_URL=http://<dsxa-host>:15000
```

Use an address that is reachable from inside the Kubernetes cluster, not only from your laptop.

## Cleanup

```bash
helm uninstall fs -n $NAMESPACE
helm uninstall $RELEASE -n $NAMESPACE
kubectl delete namespace $NAMESPACE
```

## Next Steps

* [Deploy DSX-Connect 2 with Helm](kubernetes.md)
* [Deploy Connectors for DSX-Connect 2](connectors.md)
* [Packaging Releases](../packaging-releases.md)
