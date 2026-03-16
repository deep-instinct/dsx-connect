ARG PY_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${PY_BASE_IMAGE}

# Keep base crypto up to date (addresses OpenSSL CVEs flagged by scanners)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openssl \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m appuser

WORKDIR /app

# Optional: allow overriding PyPI index via build args
ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY connectors/aws_s3/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/framework connectors/framework
COPY connectors/aws_s3/__init__.py connectors/aws_s3/
COPY connectors/aws_s3/aws_s3_async_client.py connectors/aws_s3/
COPY connectors/aws_s3/aws_s3_client.py connectors/aws_s3/
COPY connectors/aws_s3/aws_s3_connector.py connectors/aws_s3/
COPY connectors/aws_s3/config.py connectors/aws_s3/
COPY connectors/aws_s3/version.py connectors/aws_s3/
COPY connectors/aws_s3/webhook connectors/aws_s3/webhook
COPY shared/ shared/
# Optional dev/demo certs live under shared/deploy/certs; copy to /app/certs if present
COPY shared/deploy/certs/ certs/
# Ensure certs are readable by appuser (private key restricted to owner)
RUN chown -R appuser:appuser certs \
    && chmod 0644 certs/*.crt || true \
    && chmod 0600 certs/*.key || true
COPY connectors/aws_s3/start.py connectors/aws_s3/

ENV PYTHONPATH=/app
RUN mkdir -p data && chown appuser:appuser data

USER appuser

# Command is set in docker-compose-dsx-connect-all-services.yaml
