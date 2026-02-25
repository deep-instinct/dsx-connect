# Deploying DSX-Connect on Kubernetes (Helm Quickstart)

This quickstart deploys:

* DSX-Connect Core
* An in-cluster DSXA scanner
* The Filesystem Connector

The example works on any Kubernetes cluster (k3s, EKS, AKS, OpenShift, etc.).

By the end, you will:

* Access the DSX-Connect UI
* See the Filesystem connector registered
* Run your first scan


## Prerequisites

* Kubernetes 1.19+.  [Lightweight K8S Recommendations](../reference/installations/kubernetes.md)
* Helm 3+
* kubectl configured for your cluster
* DSXA appliance URL, scanner ID, and API token


## 1) Set Variables


Adjust values as needed:

```bash
export NAMESPACE=dsx-demo
export RELEASE=dsx-demo
export DSX_CONNECT_VERSION=<dsx-connect-version>
export FILESYSTEM_CONNECTOR_VERSION=<filesystem-connector-version>

export DSXA_APPLIANCE_URL=<your-dsxa-appliance>.deepinstinctweb.com
export DSXA_SCANNER_ID=<scanner id>
export DSXA_TOKEN=<DSXA DI appliance token>
```

!!! Note    
    The DSXA_ settings are exactly the same as the ones you use to deploy DSXA, for example:
    When you look in the DI Console under Settings > Deployment > Application Security, note this CLI command:
    `docker run -it --rm -e APPLIANCE_URL=selab-dpa.customers.deepinstinctweb.com -e TOKEN=<token> -e SCANNER_ID=43 -e FLAVOR='rest,config' -p 443:5000 dpa_scanner`
    APPLIANCE_URL, TOKEN, SCANNER_ID, all map to the DSXA_ variables of the same name.

## 2) Create Namespace

```bash
kubectl create namespace $NAMESPACE
```

---

## 3) Install DSX-Connect (Core + DSXA)

```bash
helm upgrade --install $RELEASE \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --namespace $NAMESPACE \
  --set dsx-connect-api.auth.enabled=false \
  --set dsxa-scanner.enabled=true \
  --set-string global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL= \
  --set-string dsxa-scanner.env.APPLIANCE_URL=$DSXA_APPLIANCE_URL \
  --set-string dsxa-scanner.env.TOKEN=$DSXA_TOKEN \
  --set-string dsxa-scanner.env.SCANNER_ID=$DSXA_SCANNER_ID \
  --set-string global.image.tag=$DSX_CONNECT_VERSION
```

Check pods:

```bash
kubectl get pods -n $NAMESPACE
```

Wait until all pods are `Running`.

✅ Core and DSXA are now deployed.


## 4) Use a HostPath Folder for Test Data (Local Dev)

For local clusters (Colima/k3s/minikube), use a hostPath so the connector can read from your local drive.

Pick a local folder and add a test file:

```bash
export HOST_SCAN_PATH=/Users/<you>/Documents/dsx-connect-test
mkdir -p "$HOST_SCAN_PATH"
echo "hello dsx" > "$HOST_SCAN_PATH/test.txt"
```

Note: ensure your local Kubernetes VM can see this path (for Colima: `colima start --mount /Users/<you>:/Users/<you>`).


## 5) Install Filesystem Connector

```bash
helm upgrade --install fs \
  oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
  --namespace $NAMESPACE \
  --set-string image.tag=$FILESYSTEM_CONNECTOR_VERSION \
  --set scanVolume.enabled=true \
  --set scanVolume.hostPath=$HOST_SCAN_PATH
```

Check logs:

```bash
kubectl logs deploy/fs-filesystem-connector-chart -n $NAMESPACE -f
```

Look for:

```
READY
```

✅ When READY appears, the connector is registered.


## 6) Access the UI

Port-forward the API:

```bash
kubectl port-forward svc/dsx-connect-api 8080:80 -n $NAMESPACE
```

Open:

```
http://localhost:8080
```

You should see:

* Filesystem connector listed
* DSXA connected


## 7) Run a Scan

1. Click **Full Scan** on the Filesystem connector card
2. Monitor the Job - Scan Results 

You should see `test.txt` scanned, and any other file in the scan path.

✅ If results appear, your Kubernetes deployment is fully operational.


## Success 🎉

You now have:

* DSX-Connect running in Kubernetes
* An in-cluster DSXA scanner
* A Filesystem connector
* A completed scan

## Next Steps

* Learn about DSX-Connect Architecture [Core Concepts](../concepts/architecture.md)
* Learn about [Connectors](../concepts/connectors.md)


## Cleanup

```bash
helm uninstall fs -n $NAMESPACE
helm uninstall $RELEASE -n $NAMESPACE
kubectl delete namespace $NAMESPACE
```
