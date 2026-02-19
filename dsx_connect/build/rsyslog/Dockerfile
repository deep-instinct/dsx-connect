FROM debian:bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends rsyslog rsyslog-gnutls ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh
ENTRYPOINT ["/usr/local/bin/start.sh"]
