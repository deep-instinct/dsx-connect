# Configuration Reference

This page highlights the most commonly used Helm values for DSX-Connect deployments.

Most Kubernetes/Helm boilerplate settings (resources, node selectors, tolerations, affinity, etc.) are available in `values.yaml` but are not repeated here.

## Where to set values

You can set values in one of three ways:

* Values file (recommended): `-f my-values.yaml`
* CLI overrides: `--set` and `--set-string`
* GitOps: values committed in a GitOps repo

Example:

```bash
helm upgrade --install dsx -n dsx-connect \
  oci://registry-1.docker.io/dsxconnect/dsx-connect-chart \
  -f my-values.yaml
```

## Global settings

The `global` section covers settings shared by one or more components.

| Name                                             | Description                                                        | Example Value                                | Common use                                                   |
| ------------------------------------------------ | ------------------------------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------ |
| `global.image.tag`                               | DSX-Connect image tag to deploy; if blank, uses chart `appVersion` | `0.3.69`                                     | Leave blank (`''`) to deploy the chart’s paired `appVersion` |
| `global.image.repository`                        | Docker repository hosting DSX-Connect images                       | `dsxconnect/dsx-connect`                     | Leave as-is unless using a private mirror                    |
| `global.env.DSXCONNECT_SCANNER__SCAN_BINARY_URL` | DSXA scan endpoint (when DSXA is external to this chart)           | `https://my-dsxa.example.com/scan/binary/v2` | Set when `dsxa-scanner.enabled=false`                        |
| `global.env.DSXCONNECT_SCANNER__AUTH_TOKEN`      | DSXA scanner API authorization token (if required by DSXA)         | `********`                                   | Use when DSXA requires API auth; otherwise leave unset       |

## dsxa-scanner

| Name                   | Description                                                                                                       | Example Value                                                      | Common use                                                        |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------- |
| `dsxa-scanner.enabled` | If `false`, DSX-Connect uses `DSXCONNECT_SCANNER__SCAN_BINARY_URL`; if `true`, deploys an in-cluster DSXA scanner | `true` / `false`                                                   | `false` for production (external DSXA), `true` for local dev/test |
| `dsxa-scanner.env.*`   | DSXA scanner environment variables, as defined in the DSX for Applications deployment guide                       | `APPLIANCE_URL: "https://your-dsxa-appliance.deepinstinctweb.com"` | Configure only when `dsxa-scanner.enabled=true`                   |

## dsx-connect-api

| Name                                  | Description                                                                              | Example Value                   | Common use                                                                |
| ------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------------- |
| `dsx-connect-api.auth.enabled`        | If `true`, DSX-Connect API requires an enrollment token for connector registration       | `true` / `false`                | Enable in most shared/staging/prod environments                           |
| `dsx-connect-api.auth.enrollment.key` | Secret key name used to read the enrollment token                                        | `ENROLLMENT_TOKEN`              | Leave default unless your Secret uses a different key                     |
| `dsx-connect-api.tls.enabled`         | If `true`, DSX-Connect API expects a TLS Secret and serves HTTPS (application-level TLS) | `true` / `false`                | Use when not terminating TLS at ingress, or when HTTPS must reach the pod |
| `dsx-connect-api.tls.secretName`      | TLS Secret name to use when `tls.enabled=true`                                           | `<release>-dsx-connect-api-tls` | Leave unset if your Secret uses the default name                          |

## dsx-connect-scan-request-worker

| Name                                                 | Description                    | Example Value                          | Common use                                |
| ---------------------------------------------------- | ------------------------------ | -------------------------------------- | ----------------------------------------- |
| `dsx-connect-scan-request-worker.enabled`            | Enable the scan request worker | `true` / `false`                       | `true`                                    |
| `dsx-connect-scan-request-worker.replicaCount`       | Number of worker pods          | `1`                                    | Increase for throughput and resilience    |
| `dsx-connect-scan-request-worker.env.LOG_LEVEL`      | Worker log level               | `debug` / `info` / `warning` / `error` | `info`                                    |
| `dsx-connect-scan-request-worker.celery.concurrency` | Worker processes per pod       | `2`                                    | Increase before increasing `replicaCount` |

## dsx-connect-verdict-action-worker

| Name                                                   | Description                      | Example Value                          | Common use                                         |
| ------------------------------------------------------ | -------------------------------- | -------------------------------------- | -------------------------------------------------- |
| `dsx-connect-verdict-action-worker.enabled`            | Enable the verdict action worker | `true` / `false`                       | `true`                                             |
| `dsx-connect-verdict-action-worker.replicaCount`       | Number of worker pods            | `1`                                    | Scale if verdict action processing backs up        |
| `dsx-connect-verdict-action-worker.env.LOG_LEVEL`      | Worker log level                 | `debug` / `info` / `warning` / `error` | `info`                                             |
| `dsx-connect-verdict-action-worker.celery.concurrency` | Worker processes per pod         | `1`                                    | Keep low unless workload requires more parallelism |

## dsx-connect-results-worker

| Name                                            | Description               | Example Value                          | Common use                                       |
| ----------------------------------------------- | ------------------------- | -------------------------------------- | ------------------------------------------------ |
| `dsx-connect-results-worker.enabled`            | Enable the results worker | `true` / `false`                       | `true`                                           |
| `dsx-connect-results-worker.replicaCount`       | Number of worker pods     | `1`                                    | Scale if results processing backs up             |
| `dsx-connect-results-worker.env.LOG_LEVEL`      | Worker log level          | `debug` / `info` / `warning` / `error` | `info`                                           |
| `dsx-connect-results-worker.celery.concurrency` | Worker processes per pod  | `1`                                    | Increase carefully; results work can be IO heavy |

## dsx-connect-notification-worker

| Name                                                 | Description                    | Example Value                          | Common use                                   |
| ---------------------------------------------------- | ------------------------------ | -------------------------------------- | -------------------------------------------- |
| `dsx-connect-notification-worker.enabled`            | Enable the notification worker | `true` / `false`                       | `true`                                       |
| `dsx-connect-notification-worker.replicaCount`       | Number of worker pods          | `1`                                    | Scale if notifications backlog               |
| `dsx-connect-notification-worker.env.LOG_LEVEL`      | Worker log level               | `debug` / `info` / `warning` / `error` | `info`                                       |
| `dsx-connect-notification-worker.celery.concurrency` | Worker processes per pod       | `1`                                    | Increase only if notifications are CPU bound |

## dsx-connect-dianna-worker

| Name                                           | Description              | Example Value                          | Common use                                    |
| ---------------------------------------------- | ------------------------ | -------------------------------------- | --------------------------------------------- |
| `dsx-connect-dianna-worker.enabled`            | Enable the DIANNA worker | `true` / `false`                       | `false` unless integrating with DI management |
| `dsx-connect-dianna-worker.replicaCount`       | Number of worker pods    | `1`                                    | Usually `1`                                   |
| `dsx-connect-dianna-worker.env.LOG_LEVEL`      | Worker log level         | `debug` / `info` / `warning` / `error` | `info`                                        |
| `dsx-connect-dianna-worker.celery.concurrency` | Worker processes per pod | `1`                                    | Usually `1`                                   |

