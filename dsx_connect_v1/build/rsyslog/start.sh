#!/bin/sh
set -e

CONF=/etc/rsyslog.conf

if [ ! -f "$CONF" ]; then
  echo "ERROR: rsyslog config not found at $CONF"
  exit 1
fi

if [ "${RSYSLOG_VALIDATE:-0}" = "1" ]; then
  echo "Validating rsyslog config with rsyslogd -N1..."
  rsyslogd -N1 -f "$CONF"
fi

echo "Starting rsyslog..."
exec rsyslogd -n -f "$CONF"
