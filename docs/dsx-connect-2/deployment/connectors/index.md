# DSX-Connect 2 Connector Deployment

Connectors register with DSX-Connect 2 and advertise the repository capabilities they support.
The control plane uses those registrations to show repository connectors, discover assets, apply protection profiles, and dispatch scans.

Deploy the DSX-Connect 2 control plane before deploying connectors:

```bash
helm upgrade --install dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  --version 2.0.2 \
  --namespace dsx-connect \
  --create-namespace \
  -f dsx-connect-values.yaml
```

Connectors running in the same namespace normally point at the in-cluster API service:

```text
http://dsx-connect-api:8091
```

## Connector Pages

* [Google Cloud Storage](google-cloud-storage.md)
* [Filesystem](filesystem.md)

## DSX-Connect 2 Registration Settings

Every connector values file should include the DSX-Connect 2 registration settings:

```yaml
env:
  DSXCONNECTOR_REGISTER_WITH_CORE: "false"
  DSXCONNECTOR_REGISTER_WITH_NG_CONTROL_PLANE: "true"
  DSXCONNECTOR_DSX_CONNECT_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_DSX_CONNECT_NG_URL: "http://dsx-connect-api:8091"
  DSXCONNECTOR_INSTANCE_ID: "connector-instance-1"
  DSXCONNECTOR_NG_PLATFORM: "<platform>"
  DSXCONNECTOR_NG_PLATFORM_KEY: "<tenant-or-project-boundary>"
```

Use a stable `DSXCONNECTOR_INSTANCE_ID` for a running connector instance.
Use `DSXCONNECTOR_NG_PLATFORM_KEY` to identify the account, project, tenant, host, or other platform boundary represented by the connector.

For local build scripts, local image loading, and helper-script deployment workflows, see [Development deployment](../development.md).
