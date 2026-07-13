FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/dsx_connect_ng \
    DSX_CONNECT_NG__SERVICE_NAME=dsx-connect

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip

COPY shared/ shared/
COPY dsxa_sdk_py/ dsxa_sdk_py/
COPY dsx_connect_ng/ dsx_connect_ng/

RUN python -m pip install --no-cache-dir -e "./dsxa_sdk_py" -e "./dsx_connect_ng[workers]"

EXPOSE 8091

CMD ["python", "-m", "uvicorn", "dsx_connect_ng.app:app", "--host", "0.0.0.0", "--port", "8091"]
