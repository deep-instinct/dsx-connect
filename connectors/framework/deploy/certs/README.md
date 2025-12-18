Central Dev TLS certs (for local HTTPS)

This folder contains a generator script and documentation. The generated cert/key
should not be committed to git.

During `docker build` (including Invoke-based builds), connector Dockerfiles may
copy cert material from `shared/deploy/certs/` into the image at `/app/certs` if it
exists in the build context. That allows convenient local HTTPS testing, but you
should prefer mounting certs at runtime for anything shared/long-lived.

- Generate self-signed certs:
  ./generate-dev-cert.sh

- Resulting files:
  - dev.localhost.crt
  - dev.localhost.key

If you want these baked into an image for local testing, copy the generated
files into `shared/deploy/certs/` before building:
  cp dev.localhost.crt ../../../shared/deploy/certs/dev.localhost.crt
  cp dev.localhost.key ../../../shared/deploy/certs/dev.localhost.key

- Enable in container via env:
  - DSXCONNECTOR_USE_TLS=true
  - DSXCONNECTOR_TLS_CERTFILE=/app/certs/dev.localhost.crt
  - DSXCONNECTOR_TLS_KEYFILE=/app/certs/dev.localhost.key

Replace with your own certs for staging/production or mount them at /app/certs.
