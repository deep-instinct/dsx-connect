# Editable metadata is pure Python. Generate it on the builder's native platform
# rather than invoking packaging backends repeatedly under target emulation.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS metadata
WORKDIR /app
COPY dsxa_sdk_py/pyproject.toml dsxa_sdk_py/README.md dsxa_sdk_py/LICENSE dsxa_sdk_py/NOTICE.md dsxa_sdk_py/
COPY dsxa_sdk_py/dsxa_sdk_py/ dsxa_sdk_py/dsxa_sdk_py/
COPY dsxa_sdk_py/examples/ dsxa_sdk_py/examples/
COPY dsx_connect_v2/ dsx_connect_v2/
RUN python -m pip install --no-cache-dir --no-deps --prefix=/opt/runtime-metadata \
    -e ./dsxa_sdk_py -e ./dsx_connect_v2

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/dsx_connect_v2 \
    DSX_CONNECT_V2__SERVICE_NAME=dsx-connect
WORKDIR /app
RUN python -m pip install --no-cache-dir --upgrade pip
COPY shared/ shared/
# Copy SDK source explicitly; never package local upload corpora or build output.
COPY --from=metadata /app/dsxa_sdk_py/ dsxa_sdk_py/
COPY --from=metadata /app/dsx_connect_v2/ dsx_connect_v2/
COPY --from=metadata /opt/runtime-metadata/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
RUN python -m pip install --no-cache-dir "dsxa-sdk-py" "dsx-connect-v2[workers,gcs]"
EXPOSE 8091
CMD ["python", "-m", "uvicorn", "dsx_connect_v2.app:app", "--host", "0.0.0.0", "--port", "8091"]
