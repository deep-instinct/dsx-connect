#!/usr/bin/env sh
set -e
CN=${CN:-localhost}
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -subj "/CN=$CN" \
  -keyout dev.localhost.key -out dev.localhost.crt
echo "Generated dev.localhost.crt and dev.localhost.key for CN=$CN"
