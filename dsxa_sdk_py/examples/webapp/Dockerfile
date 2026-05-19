FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY dsxa_sdk_py /app/dsxa_sdk_py
COPY examples /app/examples

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[webapp]"

CMD ["sh", "-c", "uvicorn examples.webapp.app:app --host 0.0.0.0 --port ${PORT}"]
