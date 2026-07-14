# Dead Letter Queues

DSX-Connect 2 uses RabbitMQ as the runtime queue boundary for scan, policy, remediation, DIANNA, and result-sink work.
For now, RabbitMQ is also the supported DLQ inspection tool.

The DSX-Connect API exposes the configured queue topology, but it does not currently browse live queue contents or replay DLQ messages.

## Queue Topology

Check the configured queue names from the DSX-Connect API:

```bash
export DSX_CONNECT_URL="https://dsx-connect.10.2.4.103.nip.io"

curl -sS "$DSX_CONNECT_URL/api/v1/execution/topology" | jq .
```

Current DLQ queue names are:

| Work family | DLQ |
| --- | --- |
| Scan | `dsx.ng.scan.dlq` |
| Policy | `dsx.ng.policy.dlq` |
| Remediation | `dsx.ng.remediation.dlq` |
| DIANNA | `dsx.ng.dianna.dlq` |
| Result sink | `dsx.ng.result_sink.dlq` |

Messages move to a DLQ when a worker failure is non-retryable or when retry attempts are exhausted.
The retry attempt count is tracked in the `x-dsx-retry-attempt` message header.

## Open RabbitMQ Management

For the embedded RabbitMQ chart, the image includes the RabbitMQ Management UI.
Forward the management service to your workstation:

```bash
export NAMESPACE=dsx-connect

kubectl port-forward -n "$NAMESPACE" svc/dsx-connect-rabbitmq 15672:15672
```

Open:

```text
http://127.0.0.1:15672
```

Use the RabbitMQ credentials from your Helm values.
The lab defaults are:

```text
dsx / dsx
```

In the console, open **Queues and Streams** and inspect queues ending in `.dlq`.

## Check DLQ Counts

The RabbitMQ Management API can list DLQ depths:

```bash
curl -u dsx:dsx 'http://127.0.0.1:15672/api/queues/%2F' \
  | jq '.[] | select(.name | endswith(".dlq")) | {name, messages, messages_ready, messages_unacknowledged}'
```

The `%2F` path segment is the URL-encoded RabbitMQ vhost `/`.

## Peek at DLQ Messages

Use `ack_requeue_true` when inspecting messages so RabbitMQ returns the messages to the DLQ after the read:

```bash
curl -u dsx:dsx \
  -H 'content-type: application/json' \
  -X POST 'http://127.0.0.1:15672/api/queues/%2F/dsx.ng.scan.dlq/get' \
  -d '{"count":5,"ackmode":"ack_requeue_true","encoding":"auto","truncate":50000}' \
  | jq .
```

Use `ack_requeue_false` only when you intentionally want to remove messages from the queue.

The payload and headers usually identify the failing job item, stage, retry count, and error.
Use that information to correct the underlying issue before restarting work.

Common scan-stage causes include:

* connector read failures
* bad connector credentials
* unreachable DSXA scanner
* missing Python package or image dependency
* source object no longer available
* invalid reader strategy or source path

## Restart a Busted Scan

DLQ replay is not implemented in DSX-Connect 2 yet.
Do not treat RabbitMQ requeue from a DLQ as the normal scan restart path, because the DSX-Connect job item state may already reflect a terminal failure.

The supported recovery flow today is:

1. Inspect the DLQ message and worker logs.
2. Fix the underlying issue.
3. Start a new scan for the affected protected scope.

From the Operator Console:

1. Open the DSX-Connect Operator Console.
2. Go to **Assets > Protected**.
3. Select the affected connector.
4. Find the protected bucket, prefix, or filesystem asset.
5. Click **Scan**.
6. Watch **Scan Results** for the new job.

You can also restart a protected scope scan through the UI API.
First find the scope:

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

For GCS and filesystem connectors, this submits a new batch for the protected scope.
If the connector supports object listing, DSX-Connect enumerates objects for the scope and queues scan items.
If listing is unavailable, DSX-Connect falls back to scanning the scope selector itself.

## Clear Resolved DLQ Messages

After the replacement scan has completed successfully and you no longer need the old failure payloads, clear the old DLQ messages from RabbitMQ intentionally.

In the RabbitMQ Management UI, open the DLQ and use the queue purge action.
From the HTTP API, use the queue delete-contents endpoint:

```bash
curl -u dsx:dsx \
  -X DELETE 'http://127.0.0.1:15672/api/queues/%2F/dsx.ng.scan.dlq/contents'
```

Only purge after you have captured any evidence you need for debugging or incident records.
