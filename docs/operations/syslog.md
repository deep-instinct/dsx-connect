# Syslog 

The `dsx-connect-results-worker` component is responsible for logging scan results to syslog.

The following guide only applies to deployments that use the bundled rsyslog chart in helm.

The default deployments include a rsyslog service that can be used to collect scan results within the cluster.  The rsyslog
service is enabled by default, but can be disabled by setting `rsyslog.enabled=false` in the `values.yaml` file.

## Syslog Format

Syslog payloads are JSON objects with these top-level fields:

- `timestamp`: UTC ISO-8601 timestamp.
- `source`: constant `dsx-connect`.
- `scan_request`: the original scan request (location, metainfo, connector, scan_job_id, size_in_bytes).
- `verdict`: DSXA verdict details (verdict, file_info, verdict_details, scan_duration_in_microseconds, etc.).
- `item_action`: connector action status (status, message, item_action).

Example payload:

```json
{
  "timestamp": "2026-02-10T23:12:34.567Z",
  "source": "dsx-connect",
  "scan_request": {
    "location": "/path/to/file.docx",
    "metainfo": "{\"bucket\":\"docs\"}",
    "connector_url": "http://filesystem-connector:8080",
    "size_in_bytes": 14844,
    "scan_job_id": "job-123"
  },
  "verdict": {
    "scan_guid": "007ea79292ae4261ad82269cd13051b9",
    "verdict": "Benign",
    "verdict_details": { "event_description": "File identified as benign" },
    "file_info": {
      "file_type": "OOXMLFileType",
      "file_size_in_bytes": 14844,
      "file_hash": "286865e7337f30ac2d119d8edc9c36f6a11552eb23c50a1137a19e0ace921e8e"
    },
    "scan_duration_in_microseconds": 10404
  },
  "item_action": {
    "status": "nothing",
    "message": "No action taken",
    "item_action": "nothing"
  }
}
```

On the wire, syslog lines are prefixed with `dsx-connect ` followed by the JSON payload. The bundled rsyslog chart extracts the JSON for output/forwarding.

## Reading Syslog Output

By default, the bundled rsyslog writes parsed scan-result JSON to stdout. That means you can observe syslog output by tailing the rsyslog pod logs, for example:

`kubectl logs -n <namespace> -l app.kubernetes.io/name=rsyslog -f`

This is the quickest way to verify scan-result messages are flowing before forwarding to an external collector.

## Forward Internal rsyslog to an External Syslog Collector

The bundled rsyslog chart supports forwarding all scan-result messages to an external syslog receiver. Enable forwarding under `rsyslog.config.forward`:

```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "syslog.example.com"
      port: 514
      tls: false
```

## Forward to Papertrail

Papertrail accepts standard syslog over TCP or TLS. Use the hostname/port from your Papertrail log destination.

TCP (no TLS):
```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "logsN.papertrailapp.com"
      port: 514
      tls: false
```

TLS (recommended by Papertrail):
```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "logsN.papertrailapp.com"
      port: 6514
      tls: true
      permittedPeer: "*.papertrailapp.com"
```

TLS forwarding requires an rsyslog image with the `gtls` module. See the Developer's Guide: [Rsyslog TLS Image](rsyslog-tls-image.md).

Notes:

- Replace `logsN.papertrailapp.com` with your Papertrail destination hostname.
- If you enable TLS, ensure `permittedPeer` matches the certificate name used by your destination.

## Forward to SolarWinds Observability (token-based syslog)

SolarWinds Observability uses a token-based syslog format. Set `format` to `solarwinds` and provide the destination token.

```yaml
rsyslog:
  config:
    forward:
      enabled: true
      target: "syslog.collector.na-01.cloud.solarwinds.com"
      port: 6514
      tls: true
      permittedPeer: "*.collector.na-01.cloud.solarwinds.com"
      format: "solarwinds"
      token: "<your-syslog-token>"
```

