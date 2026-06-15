# Rsyslog TLS Image (gtls)

The bundled rsyslog chart forwards scan results to external syslog collectors. If you enable TLS forwarding, rsyslog must have the `gtls` module available. The stock `rsyslog/rsyslog` image does not ship with `gtls`, so you need to build a small derivative image.

## Dockerfile

The Dockerfile lives at:

`dsx_connect/build/rsyslog/Dockerfile`

Contents:

```Dockerfile
FROM rsyslog/rsyslog:latest

RUN apt-get update \
  && apt-get install -y --no-install-recommends rsyslog-gnutls ca-certificates \
  && rm -rf /var/lib/apt/lists/*
```

## Build and push

```bash
docker build -t dsxconnect/rsyslog-gnutls:<tag> \
  -f dsx_connect/build/rsyslog/Dockerfile .
docker push dsxconnect/rsyslog-gnutls:<tag>
```

## Use the image in Helm

```yaml
rsyslog:
  image:
    repository: dsxconnect/rsyslog-gnutls
    tag: "<tag>"
```

## Use the image in Docker Compose

If you run the bundled rsyslog via compose, set the rsyslog service image to the TLS-capable tag (edit the compose file or use an override file):

```yaml
services:
  rsyslog:
    image: dsxconnect/rsyslog-gnutls:<tag>
```
