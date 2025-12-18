# Kubernetes Deployment Best Practices

Use this page as the single checklist before diving into the connector-specific guides. It covers the cluster requirements, where to fetch Helm charts, and the high-level deployment workflow shared by every dsx-connect component.

## Prerequisites
- Kubernetes 1.19+ (tested on k3s/AKS/EKS/GKE)
- Helm 3.2+ and `kubectl`
- Cluster admin rights to create namespaces, Secrets, and ServiceAccounts
- Access to the dsx-connect Helm charts hosted in Docker Hub’s OCI registry: [https://hub.docker.com/r/dsxconnect](https://hub.docker.com/r/dsxconnect)
- Connector-specific credentials (for example: AWS IAM keys, Azure AD app secrets, GCP service-account JSON; see Reference pages for each provider)

## Kubernetes Secrets and Credentials
Prefer Kubernetes-native secret handling over `.env` files or committing credentials to `values.yaml`.

Recommended approaches (pick one that fits your operating model):

- **Kubernetes Secrets** (baseline): create `Secret` objects and reference them from Helm values (for example, `envSecretRefs`).
- **External Secrets Operator** (recommended in cloud): sync secrets from AWS Secrets Manager / Azure Key Vault / Google Secret Manager into Kubernetes Secrets automatically.
- **Sealed Secrets / SOPS** (GitOps-friendly): store encrypted secret manifests in git; decrypt only in-cluster or during CI.

Practical tips:

- Avoid putting secrets on the command line (`--set`, `--from-literal`) when possible; they can end up in shell history, CI logs, or process lists.
- Prefer `kubectl apply -f -` from stdin (or pre-created manifest files) for repeatable, audit-friendly deployments.
- Scope secrets tightly: use one namespace per environment and least-privilege RBAC for ServiceAccounts that read Secrets.
- Plan rotation: keep Secret names stable and rotate values, then `helm upgrade` / restart Pods so deployments re-read updated data.

Example: create a connector env Secret from a local env file:
```bash
kubectl create secret generic aws-s3-connector-env \
  --from-env-file=.env.aws-s3 \
  --namespace your-namespace
```

## Helm chart locations
The `inv release-all` pipeline publishes every chart to Docker Hub under the `dsxconnect` namespace. Browse the full catalog (images and charts) at [https://hub.docker.com/r/dsxconnect](https://hub.docker.com/r/dsxconnect). Pull/install specific charts directly with Helm’s OCI support.

| Example component | OCI reference | Example install |
| --- | --- | --- |
| dsx-connect core (API + workers) | `oci://registry-1.docker.io/dsxconnect/dsx-connect-chart` | `helm install dsx oci://registry-1.docker.io/dsxconnect/dsx-connect-chart --version 0.3.44 -f your-values.yaml` |
| Filesystem connector | `oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart` | `helm install fs oci://registry-1.docker.io/dsxconnect/filesystem-connector-chart --version 0.5.25` |
| Google Cloud Storage connector | `oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart` | `helm install gcs oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart --version 0.5.25 --set env.DSXCONNECTOR_ASSET=my-bucket` |
| SharePoint connector | `oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart` | `helm install sp oci://registry-1.docker.io/dsxconnect/sharepoint-connector-chart --version 0.5.25` |

> **Tip:** Use `helm pull <oci-url> --version X --untar` if you want to download the chart, inspect or customize a chart locally before installing.

## Deployment flow
1. **Prepare secrets:** Create Kubernetes Secrets for enrollment tokens, connector credentials (AWS keys, Azure app secrets, GCP JSON), and any TLS bundles. Each connector guide links to the exact `kubectl create secret` commands.
2. **Deploy dsx-connect core:** Follow [dsx-connect (Helm)](dsx-connect.md) to install the API, workers, Redis, and syslog stack. Verify `/readyz` and watch the UI before layering connectors.
3. **Deploy connectors:** Pick the connector guide under this section (Filesystem, AWS S3, Azure Blob, Google Cloud Storage, SharePoint, OneDrive, etc.). Each page documents the required values, secrets, and network exposure.
4. **Ingress & auth:** Configure your cluster ingress controller (NGINX, ALB, etc.) and, where required, expose only the connector webhook path. Front the dsx-connect UI/API with your organization’s SSO or oauth2-proxy.
5. **Monitoring & rotation:** Enable Prometheus/Syslog targets if you have centralized logging, and plan secret rotations (enrollment token CSVs, connector credentials, DSX-HMAC reprovisioning) as described in [Deployment → Authentication](../deployment/authentication.md).


This keeps sensitive data in Secrets and simplifies upgrades (`helm upgrade -f values-prod.yaml`).

## Reusing `.env` files from Compose / Helm
If you already maintain `.env` files for Docker Compose, convert them directly into Kubernetes Secrets:

1. Keep your connector settings in a `KEY=value` file such as `.env.aws-s3` (see Docker Quickstart step 4 for an example layout).
2. Create a Secret:  
   ```bash
   kubectl create secret generic aws-s3-connector-env \
     --from-env-file=.env.aws-s3 \
     --namespace your-namespace
   ```
3. Reference it via the chart, e.g.:
   ```yaml
   envSecretRefs:
     - aws-s3-connector-env
   auth_dsxconnect:
     enabled: true
     enrollmentSecretName: aws-s3-connector-env
     enrollmentKey: DSXCONNECT_ENROLLMENT_TOKEN
   ```

This way Docker Compose, Helm, and GitOps overlays can all pull from the same source of truth.

## Next steps
- Deploy dsx-connect core via [dsx-connect (Helm)](dsx-connect.md).
- Choose the connector page that matches your repository (Filesystem, AWS S3, Azure Blob Storage, Google Cloud Storage, SharePoint, OneDrive, M365 Mail, etc.).
- Review [Deployment → Authentication](../authentication.md) for the enrollment + DSX-HMAC model used by every connector.

Once the core stack is online and at least one connector is registered, log into the dsx-connect UI to monitor health, run scans, and verify webhook activity.
