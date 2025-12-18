# DSX-Connect and AWS S3 Connector on K8S Tutorial

This quickstart runs on a lightweight k3s cluster via Colima to keep things simple, but the same steps work on any Kubernetes cluster. We’ll deploy dsx-connect (with auth enabled so only enrollment-tokened connectors can join), the in-cluster DSXA scanner, and the AWS S3 connector. Everything comes straight from the Helm OCI charts using only CLI overrides, so you can copy/paste the commands (substituting your AWS credentials).

## Prerequisites

- Kubernetes 1.19+ cluster with working LoadBalancer/NodePort support. On macOS, [Colima](https://github.com/abiosoft/colima) with `colima start --kubernetes` is a compact local k3s option.
- Helm 3.2+, kubectl, and access to Docker Hub’s OCI registry (`helm registry login registry-1.docker.io`).
- AWS access key/secret with read/write access to a test bucket and at least one sample file already in the bucket.
- DSXA appliance URL, scanner ID, and API token that you are allowed to use for testing.

## 1. Set variables and namespace

```bash
export NAMESPACE=dsx-tutorial-1
export RELEASE=dsx-tutorial-1
export AWS_BUCKET=my-demo-bucket      # replace with a real bucket
export ENROLLMENT_TOKEN=$(uuidgen)    # or any strong random string
export DSXA_APPLIANCE_URL=your-dsxa-appliance.example.com
export DSXA_SCANNER_ID=1
export DSXA_TOKEN=changeme

kubectl create namespace $NAMESPACE
```

## 2. Create secrets

### Enrollment token

```bash
kubectl create secret generic ${RELEASE}-dsx-connect-api-auth-enrollment \
  -n $NAMESPACE \
  --from-literal=ENROLLMENT_TOKEN="$ENROLLMENT_TOKEN"
```

> The dsx-connect chart always looks for a Secret named `<release>-dsx-connect-api-auth-enrollment` with a key called `ENROLLMENT_TOKEN`, so keep that convention when you create it.

### AWS env + connector config

Export your AWS creds (or pull them from `~/.aws/credentials` manually) so the heredoc can reference them:

```bash
export AWS_ACCESS_KEY_ID=<your-access-key>
export AWS_SECRET_ACCESS_KEY=<your-secret-key>
```
**Note:** If you already have a profile in `~/.aws/credentials`, you can pull the values directly:
```bash
export AWS_ACCESS_KEY_ID=$(aws configure get default.aws_access_key_id)
export AWS_SECRET_ACCESS_KEY=$(aws configure get default.aws_secret_access_key)
```

Create a temporary file (do not commit this):

```bash
cat <<EOF > .env.aws-creds
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
EOF
```

```bash
kubectl create secret generic aws-credentials \
  --from-env-file=.env.aws-creds \
  -n $NAMESPACE
```

_Optional:_ If you prefer editing YAML directly or storing secrets in source control, you can create the Secret like this instead:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials  # default name expected by the Helm chart
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "<your-access-key-id>"
  AWS_SECRET_ACCESS_KEY: "<your-secret-access-key>"
```

Save it as `aws-secret.yaml`, edit the values, and apply with `kubectl apply -f aws-secret.yaml`.

## 3. Install dsx-connect (API + DSXA)

Enables authentication and the bundled DSXA scanner:

```bash
helm upgrade --install $RELEASE \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --namespace $NAMESPACE \
  --set dsxa-scanner.enabled=true \
  --set dsx-connect-api.auth.enabled=true \
  --set-string dsxa-scanner.env.APPLIANCE_URL=$DSXA_APPLIANCE_URL \
  --set-string dsxa-scanner.env.TOKEN=$DSXA_TOKEN \
  --set-string dsxa-scanner.env.SCANNER_ID=$DSXA_SCANNER_ID \
  --set-string global.image.tag=0.3.46
```
> Example versions: the `0.3.46` tag should match the dsx-connect chart/appVersion you intend to run.

For production, store DSXA info in a Kubernetes Secret and use `values.yaml` or `helm upgrade --set-file` so tokens are not exposed in shell history. Here we keep everything inline for clarity.

Check pods:

```bash
kubectl get pods -n $NAMESPACE
```

## 4. Install AWS S3 connector

```bash
helm upgrade --install aws-s3 \
  oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart \
  --namespace $NAMESPACE \
  --set-string env.DSXCONNECTOR_ASSET=$AWS_BUCKET \
  --set auth_dsxconnect.enabled=true \
  --set auth_dsxconnect.enrollmentSecretName=${RELEASE}-dsx-connect-api-auth-enrollment \
  --set auth_dsxconnect.enrollmentKey=ENROLLMENT_TOKEN \
  --set-string image.tag=0.5.27
```
> Replace `0.5.27` with the AWS connector version you plan to run.

Watch logs until the connector reports READY:

```bash
kubectl logs deploy/aws-s3-aws-s3-connector-chart -n $NAMESPACE -f | grep READY
```

## 5. Access the UI and test

Port-forward the dsx-connect API/UI:

```bash
kubectl port-forward svc/dsx-connect-api 8080:80 -n $NAMESPACE
```

Port-forwarding is a quick way to expose a service for local testing only. In real deployments you’d configure an Ingress controller, LoadBalancer service, or some other edge proxy based on your cluster environment. We will provide examples throughout the guides, but the exact setup is cluster-dependent.

Visit `http://localhost:8080`, confirm the AWS connector shows READY, and launch a Full Scan from the UI. Files already in `$AWS_BUCKET` should queue. 

Note: Webhook/on-access tests require S3 event wiring, which is beyond the scope of this quickstart.  See the Connector deployment for AWS S3 for more details.


## Cleanup

```bash
helm uninstall aws-s3 -n $NAMESPACE
helm uninstall $RELEASE -n $NAMESPACE
kubectl delete namespace $NAMESPACE
rm .env.aws-creds
```
