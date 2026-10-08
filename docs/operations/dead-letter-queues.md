# Failed Scans and Dead Letter Queues

DSX-Connect 2 uses RabbitMQ as the runtime queue boundary for scan, policy, remediation, DIANNA, and result-sink work.
When work fails, it ends up in one of two places depending on the kind of failure.
Knowing which one tells you where to look.

## Where Failures Go

| Failure | Example | What happens | Where to look |
| --- | --- | --- | --- |
| Retryable | connector or DSXA briefly unreachable | Retried up to 5 times, 5 seconds apart, through the `.retry` queue | Worker logs; the queue depth looks stalled while retries cycle |
| Retryable, attempts exhausted | DSXA down for longer than the retry window | Moved to the stage's `.dlq` queue | RabbitMQ DLQ |
| Known terminal scan failure | DSXA rejects the auth token, object no longer exists, missing scanner configuration | Job item marked `failed` with an error code; message acknowledged | Job items API or Operator Console, **not** the DLQ |
| Unexpected terminal failure | unhandled worker error | Moved to the `.dlq` queue with header `x-dsx-terminal: true` | RabbitMQ DLQ |

An empty DLQ does not mean a scan succeeded.
Always check failed job items first.

Retry limits come from the RabbitMQ settings on the workers:

| Setting | Default |
| --- | --- |
| `DSX_CONNECT_V2_RABBITMQ__RETRY_MAX_ATTEMPTS` | `5` |
| `DSX_CONNECT_V2_RABBITMQ__RETRY_DELAY_MS` | `5000` |

The current attempt number is carried in the `x-dsx-retry-attempt` message header.

## Check Failed Job Items

Set the API URL. With a port-forward to the API service this is `http://127.0.0.1:8091`:

```bash
export DSX_CONNECT_URL="http://127.0.0.1:8091"
```

Find recent jobs:

```bash
curl -sS "$DSX_CONNECT_URL/api/v1/execution/jobs" \
  | jq '.[] | {job_id, job_type, state, scope_id}'
```

Check job progress, including the failed item count:

```bash
export JOB_ID="<job-id>"

curl -sS "$DSX_CONNECT_URL/api/v1/execution/jobs/$JOB_ID/progress" \
  | jq '{state, item_summary}'
```

Group failed items by error code:

```bash
curl -sS "$DSX_CONNECT_URL/api/v1/execution/jobs/$JOB_ID/items?limit=10000" \
  | jq '[.[] | select(.scan_state == "failed")]
        | group_by(.scan_error.code)
        | map({code: .[0].scan_error.code, count: length, example: .[0].scan_error.message})'
```

Common scan error codes:

| Code | Usual cause | Fix |
| --- | --- | --- |
| `scanner_auth_failed` | DSXA requires a scan auth token and none, or the wrong one, is configured | Set `DSX_CONNECT_V2_SCANNER__DSXA_AUTH_TOKEN` from a Secret through `envSecretRefs` |
| `scanner_transport_failure` | DSXA unreachable or restarting | Check the DSXA REST pod; lower scan worker `--prefetch-count` if DSXA restarts under load |
| `scan_execution_failed` with `connector proxy transport failure` | Scan workers cannot reach the connector address stored on the integration | Compare `config.reader.proxy.endpoint_url` on the integration with the connector service |
| `scanner_base_url_required` | `DSX_CONNECT_V2_SCANNER__BASE_URL` not set in `dsxa` mode | Set the scanner URL |

## Open RabbitMQ Management

The embedded RabbitMQ image includes the Management UI.
Forward the management port to your workstation:

```bash
export NAMESPACE=dsx-connect

kubectl port-forward -n "$NAMESPACE" svc/dsx-connect-rabbitmq 15672:15672
```

On OpenShift, `oc port-forward` takes the same arguments.

Open `http://127.0.0.1:15672`, sign in, and go to **Queues and Streams**.
DLQs end in `.dlq`.

### RabbitMQ Credentials

The embedded RabbitMQ login comes from the Helm values:

```yaml
rabbitmq:
  auth:
    username: dsx
    password: dsx
```

The chart passes these to the RabbitMQ container as `RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS`.
The lab default is `dsx` / `dsx`.

The same credentials must appear in the URL that DSX-Connect uses to connect, for example:

```yaml
env:
  DSX_CONNECT_V2_RABBITMQ__URL: "amqp://dsx:dsx@dsx-connect-rabbitmq:5672/%2F"
```

Keep the following in mind:

* RabbitMQ only creates the default user when its data directory is empty. With `rabbitmq.persistence.enabled: true`, changing `rabbitmq.auth` later does not change the existing user. Change the password with `rabbitmqctl change_password`, then update the URL.
* The values are rendered as plain environment variables, so anyone who can read the Deployment can read them. Change the defaults for any shared environment, and use an externally managed RabbitMQ for production.

To read the current user from a running release:

```bash
kubectl get deploy -n "$NAMESPACE" dsx-connect-rabbitmq \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="RABBITMQ_DEFAULT_USER")].value}'
```

## Check DLQ Counts

Without the Management UI, from the RabbitMQ pod:

```bash
kubectl exec -n "$NAMESPACE" deploy/dsx-connect-rabbitmq -- \
  rabbitmqctl list_queues name messages messages_unacknowledged consumers
```

With the Management API:

```bash
curl -u dsx:dsx 'http://127.0.0.1:15672/api/queues/%2F' \
  | jq '.[] | select(.name | endswith(".dlq")) | {name, messages, messages_ready, messages_unacknowledged}'
```

The `%2F` path segment is the URL-encoded RabbitMQ vhost `/`.

Current DLQ names:

| Work family | DLQ |
| --- | --- |
| Scan | `dsx.ng.scan.dlq` |
| Policy | `dsx.ng.policy.dlq` |
| Remediation | `dsx.ng.remediation.dlq` |
| DIANNA | `dsx.ng.dianna.dlq` |
| Result sink | `dsx.ng.result_sink.dlq` |

The configured topology is also available from the API:

```bash
curl -sS "$DSX_CONNECT_URL/api/v1/execution/topology" | jq .
```

## Peek at DLQ Messages

Use `ack_requeue_true` so RabbitMQ returns the messages to the DLQ after the read:

```bash
curl -u dsx:dsx \
  -H 'content-type: application/json' \
  -X POST 'http://127.0.0.1:15672/api/queues/%2F/dsx.ng.scan.dlq/get' \
  -d '{"count":5,"ackmode":"ack_requeue_true","encoding":"auto","truncate":50000}' \
  | jq '.[] | {headers: .properties.headers, payload: (.payload | fromjson? // .payload)}'
```

Use `ack_requeue_false` only when you intentionally want to remove messages from the queue.

The payload identifies the job, job item, and object.
The headers show `x-dsx-retry-attempt` and, for unexpected terminal failures, `x-dsx-terminal`.
Match the job item ID against the worker logs to find the error.

## Pause a Failing Scan

If every item is failing for the same reason, such as a bad scanner token, stop the scan workers so the remaining queued items are not consumed and marked failed:

```bash
kubectl scale -n "$NAMESPACE" deploy/dsx-connect-scan --replicas=0
```

Queued messages stay in `dsx.ng.scan`.
Fix the cause, then scale the workers back up.
A `helm upgrade` also restores the configured replica count.

## Restart a Failed Scan

DLQ replay is not implemented in DSX-Connect 2 yet.
Do not requeue DLQ messages through RabbitMQ to restart work, because the DSX-Connect job item state may already be terminal.

The supported recovery flow:

1. Find the failure in failed job items or the DLQ.
2. Fix the underlying issue.
3. Start a new scan for the affected protected scope.

From the Operator Console:

1. Go to **Assets > Protected**.
2. Select the affected connector.
3. Find the protected bucket, prefix, or filesystem asset.
4. Click **Scan**.
5. Watch **Scan Results** for the new job.

From the API, find the scope:

```bash
curl -sS "$DSX_CONNECT_URL/api/v1/control-plane/scopes" \
  | jq '.[] | {scope_id, integration_id, resource_selector, enabled}'
```

Then submit a new scan:

```bash
export SCOPE_ID="<scope-id>"

curl -sS \
  -H 'content-type: application/json' \
  -X POST "$DSX_CONNECT_URL/api/v1/ui/scopes/$SCOPE_ID/scan" \
  -d '{"reader_strategy":"proxy","limit":10000}' \
  | jq .
```

If the connector supports object listing, DSX-Connect enumerates objects for the scope and queues scan items.
If listing is unavailable, DSX-Connect falls back to scanning the scope selector itself.

## Clear Resolved DLQ Messages

After the replacement scan completes and you no longer need the old failure payloads, purge the DLQ.
Capture any evidence you need for debugging or incident records first.

In the Management UI, open the DLQ and use **Purge Messages**.
From the HTTP API:

```bash
curl -u dsx:dsx \
  -X DELETE 'http://127.0.0.1:15672/api/queues/%2F/dsx.ng.scan.dlq/contents'
```
