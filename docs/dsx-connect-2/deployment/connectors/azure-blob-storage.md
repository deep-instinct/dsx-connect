# Azure Blob Storage Connector

Deploy `azure-blob-storage-connector-chart` to discover containers and read blob content through DSX-Connect 2. The current chart uses a Kubernetes Secret containing an Azure Storage connection string. This guide covers the chart in this repository; it does not assume a managed-identity deployment path.

## Prerequisites

- A running DSX-Connect 2 control plane, workers, and scanner.
- Kubernetes, Helm with OCI support, and network access to the storage account and DSX-Connect API.
- A storage connection string with the access required for the selected operations: container discovery, blob listing, and reads. Remediation additionally requires the relevant delete, write/copy, or tag permissions.
- A configured container or `container/prefix`. This is important for the current adapter's repository check and fallback enumeration/read behavior.

Provision the connection string through your secret-management workflow. The Secret must be in the connector namespace and have the key `AZURE_STORAGE_CONNECTION_STRING`. For a local setup, an existing protected file can provide the value:

```bash
kubectl create namespace dsx-connect --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic azure-storage-connection-string \
  --namespace dsx-connect \
  --from-file=AZURE_STORAGE_CONNECTION_STRING=/secure/path/azure-connection-string
```

Keep credential values out of Helm values and source control.

## Deployment values

Save as `azure-blob-values.yaml`, replacing the account label and container/prefix:

```yaml
fullnameOverride: azure-blob-connector
secrets:
  name: azure-storage-connection-string
workers: 1
replicaCount: 1
env:
  LOG_LEVEL: "info"
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_V2_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "azure-blob-prod-1"
  DSXCONNECTOR_PLATFORM: "azure_blob_storage"
  DSXCONNECTOR_PLATFORM_KEY: "example-storage-account"
  DSXCONNECTOR_DISPLAY_NAME: "Example Azure Blob"
  DSXCONNECTOR_ASSET: "example-container/incoming"
  DSXCONNECTOR_FILTER: ""
  DSXCONNECTOR_ITEM_ACTION: "nothing"
  DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "dsxconnect-quarantine"
```

The chart constructs the advertised connector URL from its service name and port. The API URLs above assume the same namespace. Configure TLS, authentication, trusted CAs, and network policy for your deployment. The platform key labels the boundary; access comes from the storage credential.

A fixed `DSXCONNECTOR_INSTANCE_ID` is suitable for this single-replica example. Do not scale multiple replicas with the same fixed instance ID. `workers` controls processes per pod, not the number of protected scopes.

## Install

The repository chart is version `2.0.2`. The OCI chart name is **azure-blob-storage-connector-chart**:

```bash
helm upgrade --install azure-blob \
  oci://registry-1.docker.io/dsxconnect/azure-blob-storage-connector-chart \
  --version 2.0.2 \
  --namespace dsx-connect \
  -f azure-blob-values.yaml

kubectl rollout status deployment/azure-blob-connector -n dsx-connect --timeout=120s
kubectl logs deployment/azure-blob-connector -n dsx-connect --tail=100
```

Pin an approved published chart version; the image defaults to the chart's `appVersion`.

## Discovery and current scan limitations

The adapter exposes containers using the shared `bucket` asset type. Inventory discovery lists accessible containers; `configured_asset` exposes the configured container or container/prefix. Discovery and protection are separate decisions.

The current Azure adapter provides a configured-asset preview but does not implement the scope-aware object-listing handler used by newer adapters. The console's bounded count preview therefore reports count unavailable. Its scan fallback enumerates the configured container/prefix, rather than providing a general multi-container, scope-aware enumeration guarantee.

Start with a deployment dedicated to the intended configured container/prefix, and keep its protected scope aligned with that configuration. Do not infer that every discovered container can be scanned correctly through the same deployment merely because discovery lists it. Validate reads and targets with a small detect-only scan before expanding coverage.

In v2, the assigned protection profile supplies requested remediation actions. `DSXCONNECTOR_ITEM_ACTION` is a legacy/fallback default, not a substitute for reviewing the effective profile. Keep the initial profile detect-only and verify any intended move, tag, or delete behavior separately on disposable test content.

## Verification

1. Confirm the Kubernetes rollout and expected connector version.
2. Check **Assets > Connectors** for registration and heartbeats.
3. Open its asset view and check the configured container/prefix. Container listing can require broader access than reading one known container.
4. Protect the matching configured scope with a detect-only profile.
5. Run a small scan and inspect actual object identities, content-read failures, verdicts, and enumeration limits.

For local probe checks, forward the HTTP service from another terminal:

```bash
kubectl port-forward -n dsx-connect service/azure-blob-connector 8610:80
```

```bash
curl --fail http://127.0.0.1:8610/azure-blob-storage-connector/healthz
curl --fail http://127.0.0.1:8610/azure-blob-storage-connector/readyz
```

Liveness only confirms the process responds. Readiness and repository checks do not prove that every blob is readable or remediation is authorized. Follow [Operating connectors and scans](../../operations/connectors-and-scans.md) for scan confirmation and View/Cancel controls.

## Monitoring and tuning

Do not assume this chart enables Azure Event Grid monitoring. The adapter includes a generic webhook handler, but the current implementation does not establish a complete Event Grid subscription/validation flow. Provider event integration needs separate implementation and verification; discovery alone does not provide ongoing monitoring.

`DSXCONNECTOR_SCAN_CONCURRENCY`, `DSXCONNECTOR_LIST_PAGE_SIZE`, and `DSXCONNECTOR_DOWNLOAD_MAX_CONCURRENCY` tune connector enumeration/enqueue or download behavior. They do not raise the console's 10,000-object submission limit. Tune against storage throttling, worker capacity, and scan outcomes.

## Troubleshooting and removal

| Symptom | Check |
| --- | --- |
| `CreateContainerConfigError` | Secret name, namespace, and `AZURE_STORAGE_CONNECTION_STRING` key. |
| Not registered | Explicit v2 flags, API address/port, authentication, and network access. |
| Container discovery fails | Credential's listing permission and storage account connectivity. |
| Repository check or reads fail | Configured container/prefix, credential validity, read permissions, and actual job object identities. |
| Count unavailable | Expected with this adapter's current lack of scope-aware object listing. |
| No continuous monitoring | An event subscription is not configured by this chart; see the monitoring limitation above. |

Remove through Helm/GitOps:

```bash
helm uninstall azure-blob -n dsx-connect
```

Registration history can remain after the workload stops. Cancel active scans separately when needed; uninstalling is not a scan cancellation request.
