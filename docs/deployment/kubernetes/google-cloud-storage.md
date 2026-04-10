# Google Cloud Storage Connector — Helm Deployment

{% include-markdown "shared/connectors/google-cloud-storage/_intro.md" %}

--- 

## Prerequisites

{% include-markdown "shared/connectors/google-cloud-storage/_prerequisites.md" %}

---

## Minimal Deployment

The following steps will install the connector with minimal configuration changes, supporting full-scan only.

### Create the GCP service-account Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gcp-sa
type: Opaque
stringData:
  service-account.json: |
    { ...your JSON key... }
```

```bash
kubectl apply -f connectors/google_cloud_storage/deploy/helm/examples/gcp-sa-secret.yaml
```

### Deploy

=== "Quick Install"

    Minimal install using Helm CLI overrides.

    ```bash
    helm install gcs-dev oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart \
    --version <chart-version> \
    --set env.DSXCONNECTOR_ASSET=my-bucket/prefix \
    --set-string env.DSXCONNECTOR_FILTER="" 
    ```

    !!! note "--version"
        The version number is the chart version; removing it installs the latest chart version.

=== "values.yaml Install"

    Use a values file when deploying in production or GitOps workflows.

    First, pull the chart:
    
    ```bash 
    helm pull oci://registry-1.docker.io/dsxconnect/google-cloud-storage-connector-chart --version <connector_version> --untar
    ```
    !!! note "--version"
        The version number is the chart version; removing it uses the latest chart version.


    Edit the `values.yaml` within the untarred chart directory. Start by setting the storage and path alignment:

    > excerpt of relevant values.yaml env settings:

    ```yaml
    env:
      DSXCONNECTOR_ASSET: my-bucket/prefix
      DSXCONNECTOR_FILTER: ""  # no filter set here
      DSXCONNECTOR_ITEM_ACTION: nothing
    ```

    **Relevant env settings:**
    
    ```yaml
    env:
      DSXCONNECTOR_ASSET: my-bucket/prefix
      DSXCONNECTOR_FILTER: ""  # no filter set
      DSXCONNECTOR_ITEM_ACTION: nothing
    ```

    ??? note "Full example (env section)"
        ```yaml
        env:
            LOG_LEVEL: "debug"
            # Connector environment mode: dev | stg | prod
            DSXCONNECTOR_APP_ENV: "dev"
            # Optional friendly display name shown in the dsx-connect UI card
            # DSXCONNECTOR_DISPLAY_NAME: "Google Cloud Storage Connector"
            DSXCONNECTOR_TLS_CERTFILE: "/app/certs/tls.crt"
            DSXCONNECTOR_TLS_KEYFILE: "/app/certs/tls.key"
            # DSXCONNECTOR_VERIFY_TLS: "true"
            # DSXCONNECTOR_CA_BUNDLE: "/app/certs/ca.pem"
            # DSXCONNECTOR_DSX_CONNECT_URL: "https://my-dsx-connect.example.com"
            DSXCONNECTOR_ITEM_ACTION: "nothing"
            DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: "dsxconnect-quarantine"
            DSXCONNECTOR_ASSET: ""          # bucket name
            DSXCONNECTOR_FILTER: ""
            DSXCONNECTOR_DATA_DIR: "/app/data"
            GCS_PUBSUB_PROJECT_ID: ""
            GCS_PUBSUB_SUBSCRIPTION: ""
        ```

    If you use `DSXCONNECTOR_ITEM_ACTION=move`, also configure where you want to move files too

    > excerpt of item action env settings:
 
    ```yaml
    env:
      DSXCONNECTOR_ITEM_ACTION: move
      DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO: /app/quarantine
    ```

    Then install with your values file (from the chart directory):

    ```bash
    helm install gcs . -f values.yaml
    ```

---

## Required Settings

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_ASSET` | Bucket or `bucket/prefix` root to scan. |
| `env.DSXCONNECTOR_FILTER` | Optional rsync-style include/exclude list relative to the asset root (see [Filter reference](../../reference/filters.md)). |
| `env.DSXCONNECTOR_ITEM_ACTION` / `env.DSXCONNECTOR_ITEM_ACTION_MOVE_METAINFO` | Remediation rules (`nothing`, `delete`, `move`, `move_tag`, `tag`). |
| `workers`, `replicaCount` | Concurrency and HA knobs. |

### Connector-specific

| Key | Description |
| --- | --- |
| `gcp.credentialsSecretName` | Secret name containing `service-account.json` (default `gcp-sa`). |
| `env.DSXCONNECTOR_DSX_CONNECT_URL` | Override dsx-connect endpoint when not using in-cluster default (`http://dsx-connect-api`). |

## Advanced Settings

### Auth

See [Using DSX-Connect Authentication](authentication.md).

### TLS

See [Deploying with SSL/TLS](tls.md).

## Monitoring Settings

Monitoring is typically Pub/Sub-based.

Enable monitoring:

| Key | Description |
| --- | --- |
| `env.DSXCONNECTOR_MONITOR` | `"true"` to enable on-access scanning via Pub/Sub. |
| `env.GCS_PUBSUB_PROJECT_ID` | GCP project ID that owns the subscription. |
| `env.GCS_PUBSUB_SUBSCRIPTION` | Subscription name or full path (`projects/<project-id>/subscriptions/<sub>`). |
| `env.GCS_PUBSUB_ENDPOINT` | Optional endpoint override (for local emulators). |

Notes:

- Pub/Sub is the recommended trigger path.
- `env.GCS_PUBSUB_PROJECT_ID` should be the project ID, not the numeric project number.
- `env.GCS_PUBSUB_SUBSCRIPTION` is the Pub/Sub subscription shown in Google Cloud Console. You can provide either:
  - the subscription name you created, for example `dsx-gcs-sub`
  - the full subscription path for that same subscription, for example `projects/<project-id>/subscriptions/dsx-gcs-sub`
- The subscription must be attached to the same topic used by the bucket notification.
- In native Pub/Sub mode, the connector consumes the subscription directly using Google's client SDK. It does not use `/webhook/event`.
- Webhook alternative is supported if you route events from Cloud Run/Functions or middleware.
- For webhook mode, keep `env.DSXCONNECTOR_MONITOR=false` and expose `ingressWebhook`.

Example:

```yaml
env:
  DSXCONNECTOR_MONITOR: "true"
  GCS_PUBSUB_PROJECT_ID: "se-project-388112"
  GCS_PUBSUB_SUBSCRIPTION: "projects/se-project-388112/subscriptions/dsx-gcs-sub"
```

{% include-markdown "shared/_common_connector.md" %}
