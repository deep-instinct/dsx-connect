import asyncio

from dsx_connect_ng.jobs.contracts import ResultSinkEmitRequested
from dsx_connect_ng.workers import delivery_worker


class _ControlPlane:
    def get_integration_or_404(self, integration_id):
        raise AssertionError("integration config should not be read when helper is patched")


class _Service:
    control_plane = _ControlPlane()


def test_deliver_gateway_gcs_posts_cached_artifact_to_connector(monkeypatch, tmp_path) -> None:
    artifact = tmp_path / "payload.txt"
    artifact.write_text("hello", encoding="utf-8")
    calls = []

    class _Response:
        status_code = 200
        text = ""

        def json(self):
            return {"status": "success", "uri": "gs://bucket-name/inbox/payload.txt"}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, data, files, headers):
            name, handle, content_type = files["file"]
            calls.append(
                {
                    "url": url,
                    "data": data,
                    "name": name,
                    "content": handle.read(),
                    "content_type": content_type,
                    "headers": headers,
                }
            )
            return _Response()

    monkeypatch.setattr(
        delivery_worker,
        "_delivery_proxy_config",
        lambda _service, _request: delivery_worker.ConnectorProxyRuntimeConfig(
            endpoint_url="http://gcs-connector/google-cloud-storage-connector/write_file",
            timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(delivery_worker.httpx, "AsyncClient", _Client)

    request = ResultSinkEmitRequested(
        job_id="job-1",
        job_item_id="item-1",
        integration_id="int-gcs",
        scope_id="scope-gcs",
        object_identity="bucket-name/inbox/payload.txt",
        result_type="workflow_summary",
        final_result={"contentSource": {"mode": "cached", "locator": str(artifact)}},
        delivery_target={
            "type": "gateway_destination",
            "platform": "gcs",
            "path": "bucket-name/inbox/payload.txt",
        },
    )

    result = asyncio.run(
        delivery_worker.deliver_gateway_gcs(
            _Service(),
            request,
            request.delivery_target.delivery_target,
        )
    )

    assert result.outcome == "delivered"
    assert result.destination == "gs://bucket-name/inbox/payload.txt"
    assert calls == [
        {
            "url": "http://gcs-connector/google-cloud-storage-connector/write_file",
            "data": {
                "bucket": "bucket-name",
                "key": "inbox/payload.txt",
                "destination": "gs://bucket-name/inbox/payload.txt",
            },
            "name": "payload.txt",
            "content": b"hello",
            "content_type": "application/octet-stream",
            "headers": {},
        }
    ]
