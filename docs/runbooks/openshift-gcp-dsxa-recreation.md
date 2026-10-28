# Recreating the OpenShift/GCP DSX/A Environment

This runbook describes how to recreate the DSX/A environment on Red Hat OpenShift running on Google Cloud Platform (GCP).

It covers:

1. Creating and preparing the GCP project
2. Creating the OpenShift cluster
3. Creating the OpenShift project
4. Configuring registry access and storage
5. Deploying DSX/A with Helm
6. Verifying the deployment

The repository contains the DSX/A Helm chart, but does not currently contain complete Terraform or Ansible automation for creating the GCP project, IAM, networking, DNS, and OpenShift cluster.

## Architecture choice

This runbook assumes **self-managed OpenShift Container Platform on GCP**, installed with OpenShift installer-provisioned infrastructure.

The chart value `GCP-OCP` means OpenShift running on GCP. It is not the same as GKE. In this mode, the chart creates an OpenShift `Route` for the REST service.

Google Cloud also supports managed OpenShift Dedicated. The managed-cluster creation process is different, but the project, namespace, registry, and Helm deployment steps after cluster creation are similar.

References:

- [Google Cloud: Create an OpenShift cluster](https://docs.cloud.google.com/openshift-cluster/create-clusters)
- [Red Hat: Installing OpenShift Container Platform on Google Cloud](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html-single/installing_on_google_cloud/index)
- [Red Hat: OpenShift installation overview](https://docs.redhat.com/en/documentation/openshift_container_platform/4.16/html/installation_overview/ocp-installation-overview)

## Prerequisites

Obtain or install the following before beginning:

- A Google Cloud account with permission to create projects, IAM resources, networks, DNS records, and Compute Engine resources
- A GCP billing account
- A Red Hat OpenShift subscription or Google Cloud Marketplace entitlement
- An OpenShift pull secret
- The `gcloud` CLI
- The `oc` CLI
- The `openshift-install` CLI
- Helm 3
- A DNS domain that can be delegated to the OpenShift cluster
- DSX/A management-server URL
- DSX/A registration token
- DSX/A scanner ID
- Access to the Deep Instinct container registry or Artifact Registry credentials

## 1. Create the GCP project

Set the project and billing variables. Replace all placeholder values.

```bash
export GCP_PROJECT="my-dsxa-ocp"
export GCP_BILLING_ACCOUNT="000000-000000-000000"
export GCP_REGION="us-central1"
export GCP_ZONE="us-central1-a"

gcloud projects create "$GCP_PROJECT"

gcloud billing projects link "$GCP_PROJECT" \
  --billing-account="$GCP_BILLING_ACCOUNT"

gcloud config set project "$GCP_PROJECT"
```

Enable the APIs commonly required for the OpenShift installation and later DSX/A operation:

```bash
gcloud services enable \
  compute.googleapis.com \
  cloudresourcemanager.googleapis.com \
  dns.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  serviceusage.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com
```

### GCP service account

Create a service account for the OpenShift installer:

```bash
gcloud iam service-accounts create openshift-installer \
  --display-name="OpenShift installer" \
  --project="$GCP_PROJECT"

export INSTALLER_SA="openshift-installer@${GCP_PROJECT}.iam.gserviceaccount.com"
```

The installer requires broad permissions unless your organization has defined custom roles. Red Hat documents the required roles and permissions in the [GCP installation guide](https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html-single/installing_on_google_cloud/index).

For a temporary lab installation, an administrator may grant the installer service account the required project-level access. For production, use the least-privilege roles approved by the cloud-security team.

Create a JSON key only if the selected installation method requires one:

```bash
gcloud iam service-accounts keys create openshift-installer.json \
  --iam-account="$INSTALLER_SA" \
  --project="$GCP_PROJECT"

export GOOGLE_APPLICATION_CREDENTIALS="$PWD/openshift-installer.json"
```

Protect this file and delete it after the installation if it is no longer required.

## 2. Create the OpenShift cluster

Create a working directory:

```bash
mkdir -p "$HOME/ocp-install/dsxa-gcp"
cd "$HOME/ocp-install/dsxa-gcp"
```

Generate the installer configuration:

```bash
openshift-install create install-config
```

Provide values similar to the following when prompted:

```yaml
apiVersion: v1
baseDomain: ocp.example.com

metadata:
  name: dsxa

platform:
  gcp:
    projectID: my-dsxa-ocp
    region: us-central1

controlPlane:
  replicas: 3

compute:
  - name: worker
    replicas: 3

pullSecret: '<red-hat-pull-secret-json>'
sshKey: '<ssh-public-key>'
```

Before installing, review the generated `install-config.yaml` and confirm:

- The GCP project and region are correct.
- The cluster name is correct.
- The base DNS domain is delegated correctly.
- The machine types and replica counts meet the intended capacity.
- The selected VPC and subnets are correct if using an existing network.
- Private-cluster, proxy, or restricted-network settings are configured if required.

Install the cluster:

```bash
openshift-install create cluster \
  --dir "$HOME/ocp-install/dsxa-gcp" \
  --log-level=info
```

Save the generated administrator password and API URL. Do not delete the installation directory; it is needed for later troubleshooting or cluster destruction.

Configure the local OpenShift client:

```bash
export KUBECONFIG="$HOME/ocp-install/dsxa-gcp/auth/kubeconfig"

oc get nodes
oc get clusterversion
oc get co
```

Wait until the cluster operators report healthy status:

- `Available=True`
- `Progressing=False`
- `Degraded=False`

## 3. Create the OpenShift project

Create a dedicated project for DSX/A:

```bash
oc new-project dsxa \
  --display-name="DSX/A Scanner" \
  --description="Deep Instinct DSX/A scanner environment"

oc project dsxa
```

Confirm the project:

```bash
oc get project dsxa
```

Do not grant additional security-context permissions unless the DSX/A image or OpenShift admission policies demonstrate that they are required. Any such exception should be reviewed by the OpenShift administrator.

## 4. Configure private image registry access

The chart defaults reference images hosted under:

```text
us-docker.pkg.dev/di-dsx-external-artifacts/dsx-docker/
```

Obtain a Google service-account JSON key or other credential authorized to pull the required images. Then create an image-pull secret:

```bash
oc create secret docker-registry deepinstinct-registry \
  --docker-server=us-docker.pkg.dev \
  --docker-username=_json_key \
  --docker-password="$(cat gcp-registry-reader.json)" \
  --docker-email="platform@example.com" \
  --namespace=dsxa
```

The DSX/A chart can reference an existing secret. Do not place the JSON key directly in a committed values file.

## 5. Verify storage

For the default deployment, scan-by-path is disabled and an external NFS or SMB share is not required.

Check the cluster storage providers:

```bash
oc get csidrivers
oc get storageclass
```

If scan-by-path is required, configure a share in the Helm values:

```yaml
rest:
  share:
    allow_scan_by_path: true
    protocol: nfs
    server: <nfs-server>
    path: <nfs-path>
    size: 300Gi
```

The current chart emits a GCP Persistent Disk CSI storage class for `GCP-OCP`. Confirm that the cluster has a compatible CSI driver before enabling this feature.

## 6. Create DSX/A Helm values

Create an environment-specific values file outside the chart or in a secured deployment repository:

```yaml
global:
  cloud_provider: GCP-OCP
  management_server_url: "https://<management-server>"
  registration_token: "<registration-token>"
  scanner_id: 1

  registry:
    enabled: true
    createSecret: false
    secret_name: deepinstinct-registry

rest:
  deployment_enabled: true
  service:
    deploy_ingress: true

  secure:
    enable_ssl_on_ocp_route: true
```

The chart is located at:

```text
dist/dsxa_deployment/dpa/dpa-chart
```

The base configuration is documented in [values.yaml](../../dist/dsxa_deployment/dpa/dpa-chart/values.yaml).

## 7. Deploy DSX/A

Install the chart:

```bash
export DSXA_NAMESPACE="dsxa"
export DSXA_CHART="$PWD/dist/dsxa_deployment/dpa/dpa-chart"

helm upgrade --install dsxa \
  "$DSXA_CHART" \
  --namespace "$DSXA_NAMESPACE" \
  --create-namespace \
  -f values-gcp-ocp.yaml \
  --wait \
  --timeout 15m
```

If the current directory is not the repository root, use an absolute path for `DSXA_CHART`.

## 8. Verify the deployment

Check Helm:

```bash
helm status dsxa -n dsxa
helm list -n dsxa
```

Check OpenShift resources:

```bash
oc get pods -n dsxa
oc get deployments -n dsxa
oc get services -n dsxa
oc get routes -n dsxa
```

Wait for the deployment:

```bash
oc rollout status deployment -n dsxa --all --timeout=15m
```

Retrieve the DSX/A route:

```bash
oc get route -n dsxa
```

Use the resulting hostname as the DSX/A REST endpoint for DSX-Connect.

Review logs if registration or readiness fails:

```bash
oc logs -n dsxa deployment/<deployment-name> --all-containers=true
oc describe pod -n dsxa <pod-name>
```

## 9. Optional TLS and DNS configuration

The chart creates an OpenShift Route. With edge termination enabled, TLS terminates at the OpenShift router:

```yaml
rest:
  secure:
    enable_ssl_on_ocp_route: true
```

For a custom hostname, configure the Route or add the appropriate hostname values supported by the chart, then create a DNS record pointing the hostname to the OpenShift router endpoint.

Confirm the route configuration:

```bash
oc describe route -n dsxa
```

If a custom certificate is required, use the organization’s approved OpenShift TLS process rather than committing certificate or private-key material to the repository.

## 10. Cleanup

To remove only the DSX/A application:

```bash
helm uninstall dsxa -n dsxa
oc delete project dsxa
```

To destroy the entire installer-provisioned cluster:

```bash
openshift-install destroy cluster \
  --dir "$HOME/ocp-install/dsxa-gcp" \
  --log-level=info
```

Review the GCP project afterward for orphaned disks, static IP addresses, DNS records, service accounts, and registry resources. Do not delete the GCP project unless that is explicitly intended.

## Current automation gap

The repository currently provides the DSX/A Helm chart and deployment configuration, but not a single end-to-end script for:

- GCP project and billing setup
- GCP IAM and service accounts
- VPC, subnet, firewall, and DNS creation
- OpenShift cluster creation
- Registry credential provisioning
- OpenShift project bootstrap

For repeatable environment recreation, the recommended future structure is:

```text
infrastructure/
  terraform/
    gcp-project/
    network/
    dns/
    openshift/
  openshift/
    project.yaml
    registry-secret-template.yaml
    values-gcp-ocp.yaml
    deploy-dsxa.sh
```

Credentials, private keys, Red Hat pull secrets, and DSX/A registration tokens must remain outside source control.
