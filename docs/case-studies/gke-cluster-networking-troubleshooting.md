# Case Study: GKE Cluster Networking Troubleshooting

This walkthrough captures a real DSX-Connect 2 lab deployment failure on GKE where DSX-Connect, PostgreSQL, RabbitMQ, and a connector were configured correctly, but the cluster network could not carry normal pod-to-service traffic.

Use this page when Kubernetes objects look healthy enough to schedule, but DSX-Connect components cannot reach each other inside the cluster.

This is not DSX-Connect deployment guidance. It is a cluster troubleshooting pattern.

## Failure Pattern

The deployment showed several symptoms at the same time:

* `helm upgrade --install --wait` timed out and left the release in `failed` state.
* DSX-Connect API and workers restarted repeatedly.
* PostgreSQL was `Running` and had a ready service endpoint.
* DSX-Connect logs showed PostgreSQL connection timeouts.
* A connector could not register with the DSX-Connect API service.
* `kubectl logs` and `kubectl exec` intermittently failed with kubelet `:10250` timeouts.
* There were no Kubernetes `NetworkPolicy` resources blocking traffic.

The important clue was that multiple independent components failed on ordinary in-cluster service connectivity. That shifted the investigation away from DSX-Connect configuration and toward cluster networking.

## Variables

Set these values for the affected cluster:

```bash
export PROJECT_ID="example-project"
export CLUSTER_NAME="example-gke"
export CLUSTER_LOCATION="us-east4"
export NAMESPACE="dsx-connect"
export RELEASE="dsx-connect"
```

For GKE, make sure `kubectl` is pointed at the cluster:

```bash
gcloud container clusters get-credentials "$CLUSTER_NAME" \
  --location "$CLUSTER_LOCATION" \
  --project "$PROJECT_ID"
```

## Confirm the Application Symptoms

Check the Helm release:

```bash
helm list -n "$NAMESPACE" --all
```

Check pods and placement:

```bash
kubectl get pods -n "$NAMESPACE" -o wide
```

Check service endpoints:

```bash
kubectl get svc,endpoints -n "$NAMESPACE"
kubectl get endpointslices -n "$NAMESPACE"
```

If the API or workers crash, inspect logs:

```bash
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-api --tail=120
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-api --previous --tail=120
```

In the GKE case that produced this walkthrough, direct log retrieval also failed:

```text
dial tcp <node-ip>:10250: i/o timeout
```

That error is not an application error. It means the Kubernetes API server could not reach the node kubelet.

If direct `kubectl logs` is blocked, use Cloud Logging:

```bash
gcloud logging read \
  "resource.type=\"k8s_container\" \
   AND resource.labels.project_id=\"${PROJECT_ID}\" \
   AND resource.labels.cluster_name=\"${CLUSTER_NAME}\" \
   AND resource.labels.namespace_name=\"${NAMESPACE}\"" \
  --project "$PROJECT_ID" \
  --limit 120 \
  --format='value(timestamp,resource.labels.container_name,severity,textPayload)'
```

The DSX-Connect API and workers were failing with:

```text
psycopg.errors.ConnectionTimeout: connection timeout expired
```

The target was the in-cluster PostgreSQL service:

```text
postgresql://dsx:dsx@dsx-connect-postgres:5432/dsx_connect_2
```

## Prove It Is Not DSX-Connect

First verify PostgreSQL itself is listening:

```bash
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-postgres --tail=80
```

Look for PostgreSQL startup lines showing it is listening on `0.0.0.0:5432` and ready to accept connections.

Then run a one-shot connectivity test from another pod:

```bash
kubectl delete pod pg-connect-test -n "$NAMESPACE" --ignore-not-found

kubectl run pg-connect-test \
  -n "$NAMESPACE" \
  --restart=Never \
  --image=postgres:16-alpine \
  --env=PGPASSWORD=dsx \
  --command -- \
  sh -c 'pg_isready -h dsx-connect-postgres -p 5432 -U dsx -d dsx_connect_2 && psql -h dsx-connect-postgres -U dsx -d dsx_connect_2 -c "select 1"'
```

Read the result:

```bash
kubectl logs -n "$NAMESPACE" pg-connect-test
kubectl describe pod -n "$NAMESPACE" pg-connect-test
```

If the test pod reports this, the problem is below DSX-Connect:

```text
dsx-connect-postgres:5432 - no response
```

Clean up the test pod:

```bash
kubectl delete pod pg-connect-test -n "$NAMESPACE" --ignore-not-found
```

## Inspect GKE Networking

Describe the cluster networking:

```bash
gcloud container clusters describe "$CLUSTER_NAME" \
  --location "$CLUSTER_LOCATION" \
  --project "$PROJECT_ID" \
  --format='yaml(network,subnetwork,clusterIpv4Cidr,servicesIpv4Cidr,privateClusterConfig,ipAllocationPolicy,masterAuthorizedNetworksConfig,networkConfig,workloadIdentityConfig)'
```

Describe the subnet:

```bash
gcloud compute networks subnets describe default \
  --region "$CLUSTER_LOCATION" \
  --project "$PROJECT_ID" \
  --format='yaml(ipCidrRange,secondaryIpRanges,privateIpGoogleAccess)'
```

List firewall rules for the VPC:

```bash
gcloud compute firewall-rules list \
  --project "$PROJECT_ID" \
  --filter='network=default' \
  --format='table(name,direction,priority,sourceRanges.list():label=SOURCE_RANGES,targetTags.list():label=TARGET_TAGS,allowed[].map().firewall_rule().list():label=ALLOW,disabled)'
```

The lab cluster had this shape:

| Setting | Example value |
| --- | --- |
| Node subnet | `10.150.0.0/20` |
| Pod secondary range | `10.125.0.0/17` |
| Service range | `34.118.224.0/20` |
| Private control plane range | `172.16.105.48/28` |
| Node network tag | `gke-gs-cluster-7e8cbb48-node` |

The VPC only had the default internal allow rule:

```text
default-allow-internal  sourceRanges=10.128.0.0/9  allow=tcp:0-65535,udp:0-65535,icmp
```

The pod CIDR `10.125.0.0/17` is outside `10.128.0.0/9`, so pods could not reliably reach service backends on nodes.

The private control plane range also lacked a narrow rule to reach node kubelet ports, which explained `kubectl logs` and `kubectl exec` failures.

## Fix With Narrow Firewall Rules

Identify the node tag first:

```bash
gcloud compute instances list \
  --project "$PROJECT_ID" \
  --filter="name~gke-${CLUSTER_NAME}" \
  --format='table(name,tags.items.list())'
```

Then create rules scoped to the cluster ranges and node tag.

Replace these values with the values from your cluster:

```bash
export NETWORK="default"
export NODE_TAG="gke-example-node-tag"
export POD_CIDR="10.125.0.0/17"
export MASTER_CIDR="172.16.105.48/28"
```

Allow pod CIDR traffic to the cluster nodes:

```bash
gcloud compute firewall-rules create dsx-gke-allow-pods \
  --project "$PROJECT_ID" \
  --network "$NETWORK" \
  --direction INGRESS \
  --priority 900 \
  --source-ranges "$POD_CIDR" \
  --target-tags "$NODE_TAG" \
  --allow tcp,udp,icmp \
  --description "Allow GKE pod CIDR traffic to cluster nodes for pod-to-pod and pod-to-service connectivity"
```

Allow the private control plane to reach kubelets:

```bash
gcloud compute firewall-rules create dsx-gke-allow-master-kubelet \
  --project "$PROJECT_ID" \
  --network "$NETWORK" \
  --direction INGRESS \
  --priority 900 \
  --source-ranges "$MASTER_CIDR" \
  --target-tags "$NODE_TAG" \
  --allow tcp:443,tcp:10250 \
  --description "Allow GKE private control plane to reach node kubelet endpoints for logs and exec"
```

Do not use broad source ranges such as `0.0.0.0/0` for kubelet access.
In Shared VPC or tightly governed environments, coordinate these rules with the network owner instead of creating them directly.

## Verify Recovery

Re-run the pod-to-PostgreSQL test:

```bash
kubectl delete pod pg-connect-test -n "$NAMESPACE" --ignore-not-found

kubectl run pg-connect-test \
  -n "$NAMESPACE" \
  --restart=Never \
  --image=postgres:16-alpine \
  --env=PGPASSWORD=dsx \
  --command -- \
  sh -c 'pg_isready -h dsx-connect-postgres -p 5432 -U dsx -d dsx_connect_2 && psql -h dsx-connect-postgres -U dsx -d dsx_connect_2 -c "select 1"'

kubectl logs -n "$NAMESPACE" pg-connect-test
kubectl delete pod pg-connect-test -n "$NAMESPACE" --ignore-not-found
```

Then verify DSX-Connect:

```bash
kubectl get pods -n "$NAMESPACE"
kubectl get svc,endpoints -n "$NAMESPACE"
kubectl logs -n "$NAMESPACE" deploy/dsx-connect-api --tail=80
```

If Helm previously timed out, reconcile the release after the cluster networking is fixed:

```bash
helm upgrade --install "$RELEASE" \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version "$DSX_CONNECT_VERSION" \
  --namespace "$NAMESPACE" \
  -f dsx-connect-values.yaml \
  --wait \
  --timeout 8m
```

## Notes From the Lab

After the firewall rules were added, the same DSX-Connect pods recovered without application changes:

* API became ready and served `/api/v1/health`.
* PostgreSQL and RabbitMQ services had ready endpoints.
* Workers stopped failing on PostgreSQL connection timeouts.
* `kubectl logs` worked again through the Kubernetes API server.
* Re-running Helm changed the release from `failed` to `deployed`.

This same pattern can also explain connector registration failures. If a connector cannot reach `http://dsx-connect-api:8091` from inside the cluster, but the service and endpoints look correct, test generic pod-to-service connectivity before changing connector credentials or DSX-Connect settings.
