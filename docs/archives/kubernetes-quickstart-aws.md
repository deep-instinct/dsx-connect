# DSX-Connect and AWS S3 Connector on K8S Tutorial

This quickstart runs on a lightweight k3s cluster via Colima to keep things simple, but the same steps work on any Kubernetes cluster. We’ll deploy dsx-connect, the in-cluster DSXA scanner, and the AWS S3 connector. Everything comes straight from the Helm OCI charts using only CLI overrides, so you can copy/paste the commands (substituting your AWS credentials).

## Prerequisites

- Kubernetes 1.19+ cluster with working LoadBalancer/NodePort support. On macOS, [Colima](https://github.com/abiosoft/colima) with `colima start --kubernetes` is a compact local k3s option.
- Helm 3.2+, kubectl, and access to Docker Hub’s OCI registry (`helm registry login registry-1.docker.io`).
- AWS access key/secret with read/write access to a test bucket and at least one sample file already in the bucket.
- DSXA appliance URL, scanner ID, and API token that you are allowed to use for testing.

## 1. Define your values
Edit the following inputs or use the defaults to your desired configuration. The values provided here will be automatically
used in the example command lines provided.

<div class="var-grid">
  <label for="var-dsx-connect-version">DSX_CONNECT_VERSION</label>
  <input id="var-dsx-connect-version" data-var-input="DSX_CONNECT_VERSION" value="0.3.73" />

  <label for="var-namespace">NAMESPACE</label>
  <input id="var-namespace" data-var-input="NAMESPACE" value="dsx-tutorial-1" />

  <label for="var-release">RELEASE</label>
  <input id="var-release" data-var-input="RELEASE" value="dsx-tutorial-1" />

  <label for="var-aws-connector-version">AWS_CONNECTOR_VERSION</label>
  <input id="var-aws-connector-version" data-var-input="AWS_CONNECTOR_VERSION" value="0.5.48" />

  <label for="var-bucket">AWS_BUCKET</label>
  <input id="var-bucket" data-var-input="AWS_BUCKET" value="my-demo-bucket" />

  <label for="var-dsxa-url">DSXA_APPLIANCE_URL</label>
  <input id="var-dsxa-url" data-var-input="DSXA_APPLIANCE_URL" value="your-dsxa-appliance.deepinstinctweb.com" />

  <label for="var-scanner-id">DSXA_SCANNER_ID</label>
  <input id="var-scanner-id" data-var-input="DSXA_SCANNER_ID" value="1" />

  <label for="var-dsxa-token">DSXA_TOKEN</label>
  <input id="var-dsxa-token" data-var-input="DSXA_TOKEN" value="changeme" />
</div>

## 2. Create namespace and secrets

### Namespace

```bash
kubectl create namespace {{NAMESPACE}}
```

If the namespace already exists, you can ignore the error.

### AWS Secret 

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
  -n {{NAMESPACE}}
```

_Optional:_ If you prefer editing YAML directly or storing secrets in source control, you can create the Secret like this instead:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: aws-credentials  # default name expected by the Helm chart
  namespace: {{NAMESPACE}}
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "<your-access-key-id>"
  AWS_SECRET_ACCESS_KEY: "<your-secret-access-key>"
```

Save it as `aws-secret.yaml`, edit the values, and apply with `kubectl apply -f aws-secret.yaml`.

## 2. Install dsx-connect (API + DSXA)

Installs dsx-connect and the bundled DSXA scanner:

```bash
helm upgrade --install {{RELEASE}} \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --namespace {{NAMESPACE}} \
  --set dsx-connect-api.auth.enabled=false \
  --set dsxa-scanner.enabled=true \
  --set-string dsxa-scanner.env.APPLIANCE_URL={{DSXA_APPLIANCE_URL}} \
  --set-string dsxa-scanner.env.TOKEN={{DSXA_TOKEN}} \
  --set-string dsxa-scanner.env.SCANNER_ID={{DSXA_SCANNER_ID}} \
  --set-string global.image.tag={{DSX_CONNECT_VERSION}}
```
> Example versions: the `{{DSX_CONNECT_VERSION}}` tag should match the dsx-connect chart/appVersion you intend to run.

For production, store DSXA info in a Kubernetes Secret and use `values.yaml` or `helm upgrade --set-file` so tokens are not exposed in shell history. Here we keep everything inline for clarity.

Check pods:

```bash
kubectl get pods -n {{NAMESPACE}}
```

## 3. Install AWS S3 connector

```bash
helm upgrade --install aws -n {{NAMESPACE}} \
  oci://registry-1.docker.io/dsxconnect/aws-s3-connector-chart \
  --namespace {{NAMESPACE}} \
  --set-string env.DSXCONNECTOR_ASSET={{AWS_BUCKET}} \
  --set-string image.tag={{AWS_CONNECTOR_VERSION}}
```
> The `image.tag` should match the AWS connector version you plan to run.

Watch logs until the connector reports READY:

```bash
kubectl logs deploy/aws-s3-aws-s3-connector-chart -n {{NAMESPACE}} -f | grep READY
```

## 4. Access the UI and test

Port-forward the dsx-connect API/UI:

```bash
kubectl port-forward svc/dsx-connect-api 8080:80 -n {{NAMESPACE}}
```

Port-forwarding is a quick way to expose a service for local testing only. In real deployments you’d configure an Ingress controller, LoadBalancer service, or some other edge proxy based on your cluster environment. We will provide examples throughout the guides, but the exact setup is cluster-dependent.

Visit `http://localhost:8080`, confirm the AWS connector shows READY, and launch a Full Scan from the UI. Files already in `$AWS_BUCKET` should queue. 

Note: Webhook/on-access tests require S3 event wiring, which is beyond the scope of this quickstart.  See the Connector deployment for AWS S3 for more details.


## Cleanup

```bash
helm uninstall aws-s3 -n {{NAMESPACE}}
helm uninstall {{RELEASE}} -n {{NAMESPACE}}
kubectl delete namespace {{NAMESPACE}}
rm .env.aws-creds
```
