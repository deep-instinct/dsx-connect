ARG PY_BASE_IMAGE=python:3.12-slim-bookworm
FROM ${PY_BASE_IMAGE}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openssl \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m appuser

WORKDIR /app

ARG PIP_INDEX_URL
ARG PIP_EXTRA_INDEX_URL
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY connectors/onedrive/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY connectors/framework connectors/framework
COPY connectors/onedrive connectors/onedrive
COPY shared/ shared/
# Optional dev/demo certs under shared/deploy/certs
COPY shared/deploy/certs/ certs/
RUN chown -R appuser:appuser certs \
    && chmod 0644 certs/*.crt || true \
    && chmod 0600 certs/*.key || true
COPY connectors/onedrive/start.py ./start.py

ENV PYTHONPATH=/app
RUN mkdir -p data && chown appuser:appuser data

USER appuser
