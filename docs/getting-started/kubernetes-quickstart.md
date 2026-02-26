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
  --set-string dsxa-scanner.env.SCANNER_ID=$DSXA_SCANNER_ID
```

Check pods:

```bash
kubectl get pods -n $NAMESPACE
```

Wait until all pods are `Running`.

✅ Core and DSXA are now deployed.


## 4) Use a HostPath Folder for Test Data (Local Dev)

Choose one option based on your local cluster:

### Option A: Colima

Use a path that exists inside the Colima VM:

```bash
export HOST_SCAN_PATH=/var/dsx-connect-test
colima ssh -- sudo mkdir -p "$HOST_SCAN_PATH"
colima ssh -- sh -lc 'echo "hello dsx" | sudo tee /var/dsx-connect-test/test.txt >/dev/null'
```

If you want to scan a macOS path (for example `/Users/<you>/Documents/dsx-connect-test`), start Colima with that mount:

```bash
colima stop
colima start --mount /Users/<you>:/Users/<you>
```

### Option B: k3s

Use a path on the k3s node host filesystem:

```bash
export HOST_SCAN_PATH=/var/dsx-connect-test
sudo mkdir -p "$HOST_SCAN_PATH"
echo "hello dsx" | sudo tee "$HOST_SCAN_PATH/test.txt" >/dev/null
```


## 5) Install Filesystem Connector

```bash
helm upgrade --install fs \
  oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart \
  --namespace $NAMESPACE \
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
