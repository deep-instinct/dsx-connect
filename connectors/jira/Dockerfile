FROM python:3.12-slim-bookworm
WORKDIR /app
COPY connectors/jira/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -m appuser
COPY connectors/framework connectors/framework
COPY connectors/jira connectors/jira
COPY shared shared
RUN mkdir -p data && chown appuser:appuser data
ENV PYTHONPATH=/app
USER appuser
EXPOSE 8680
CMD ["python", "-m", "connectors.jira.start"]
