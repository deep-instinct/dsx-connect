# Log Collectors and Fan-Out

This page collects the log-collector appendix shipped with the Helm charts. It explains how dsx-connect workers emit scan-result events over syslog and describes the reference collector deployments you can use to forward those events to your SIEMs.

- Emission: workers log JSON over syslog (TCP/TLS recommended). Key env vars:
  - `DSXCONNECT_SYSLOG__TRANSPORT=tcp|tls|udp`
  - `DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL=<collector service>`
  - `DSXCONNECT_SYSLOG__SYSLOG_SERVER_PORT=<port>`

## Option A — rsyslog (Helm subchart)

The repo includes `deploy/helm/charts/rsyslog`, a wrapper around the upstream image that listens on TCP 514 and optionally forwards to Splunk HEC or another SIEM.

Install:

```bash
helm upgrade --install rsyslog \
  dsx_connect/deploy/helm/charts/rsyslog
```

Key values:

```yaml
service:
  type: ClusterIP
  tcpPort: 514
config:
  writeToStdout: true
  forward:
    enabled: true
    target: siem.example.com
    port: 6514
    tls: true
```

Point dsx-connect at the collector (worker `.env`):

```bash
DSXCONNECT_SYSLOG__TRANSPORT=tcp
DSXCONNECT_SYSLOG__SYSLOG_SERVER_URL=rsyslog
DSXCONNECT_SYSLOG__SYSLOG_SERVER_PORT=514
```

## Option B — syslog-ng (reference config)

Example `syslog-ng.conf`:

```conf
@version: 3.38
options { chain-hostnames(no); flush-lines(1); keep-hostname(yes); };
source s_net {
  syslog(ip("0.0.0.0") transport("tcp") port(514));
  syslog(ip("0.0.0.0") transport("udp") port(514));
};
destination d_stdout { file("/dev/stdout"); };
log { source(s_net); destination(d_stdout); };
```

Add additional destinations (Splunk HEC, etc.) as needed.

## Option C — Fluent Bit (reference config)

Fluent Bit can replace rsyslog/syslog-ng and fan-out to multiple cloud services:

```ini
[INPUT]
    Name   syslog
    Mode   tcp
    Listen 0.0.0.0
    Port   514
    Parser json

[OUTPUT]
    Name   splunk
    Match  *
    Host   splunk.example.com
    Port   8088
    TLS    On
    Splunk_Token YOUR_TOKEN
    Splunk_Send_Raw On

[OUTPUT]
    Name   cloudwatch_logs
    Match  *
    region us-west-2
    log_group_name  dsx-connect
    log_stream_name dsx-${HOSTNAME}
```

## Notes

- Prefer TCP/TLS for transport; Kubernetes `kubectl port-forward` works only with TCP.
- Collectors can log to stdout for `kubectl logs` inspection and/or to persistent volumes.
- Fluent Bit, Vector, and syslog-ng all offer rich destination support; pick the collector that matches your organization’s logging stack.
