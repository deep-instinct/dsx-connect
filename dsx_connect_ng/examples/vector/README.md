# Vector Examples

These example configs show the recommended collector pattern for `dsx_connect_ng` result events:

1. DSX-Connect emits structured JSON lines through `JsonLinesResultSink`
2. Vector tails the result file
3. Vector parses and normalizes events
4. Vector forwards them to the chosen downstream sink

Recommended DSX-Connect settings:

```bash
DSX_CONNECT_NG_RESULT_SINK__BACKEND=json_lines
DSX_CONNECT_NG_RESULT_SINK__PATH=/tmp/dsx-connect-ng-results.jsonl
```

Included examples:

- `vector-console.yaml`
  - local debugging pipeline
  - tails the JSONL file and prints normalized events to stdout
- `vector-splunk-hec.yaml`
  - forwards normalized events to Splunk HEC
- `vector-chronicle.yaml`
  - forwards normalized events to Google SecOps / Chronicle

Run locally:

```bash
vector --config dsx_connect_ng/examples/vector/vector-console.yaml
```

Environment variables commonly used by these configs:

```bash
export DSX_RESULTS_PATH=/tmp/dsx-connect-ng-results.jsonl
export VECTOR_DATA_DIR=/tmp/vector-dsx-connect-ng
export SPLUNK_HEC_ENDPOINT=https://http-inputs-hec.splunkcloud.com
export SPLUNK_HEC_TOKEN=...
export CHRONICLE_CUSTOMER_ID=...
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/chronicle-service-account.json
```
