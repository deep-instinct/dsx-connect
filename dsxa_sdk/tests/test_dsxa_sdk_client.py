from typing import Any

import httpx
import pytest

from dsxa_sdk import DSXAClient, ScanMode


class MockTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "content": request.content,
            }
        )
        body = {
            "scan_guid": "guid-123",
            "verdict": "Benign",
            "verdict_details": {"event_description": "File identified as benign"},
            "file_info": {"file_type": "OOXMLFileType", "file_size_in_bytes": 10},
        }
        return httpx.Response(200, json=body)


@pytest.fixture()
def transport():
    return MockTransport()


@pytest.fixture()
def client(monkeypatch, transport):
    httpx_client = httpx.Client(transport=transport)
    monkeypatch.setattr("dsxa_sdk.client.httpx.Client", lambda **kwargs: httpx_client)
    sdk = DSXAClient(base_url="https://scanner.example.com", auth_token="token")
    yield sdk
    sdk.close()


def test_scan_binary_sends_headers(client, transport):
    resp = client.scan_binary(b"data", protected_entity=3, custom_metadata="App123")
    assert resp.scan_guid == "guid-123"
    call = transport.calls[-1]
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert call["url"].endswith("/scan/binary/v2")
    assert headers["protected_entity"] == "3"
    assert headers["x-custom-metadata"] == "App123"


def test_scan_file_base64(client, transport, tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"hello")

    client.scan_file(str(file_path), mode=ScanMode.BASE64)
    call = transport.calls[-1]
    assert call["url"].endswith("/scan/base64/v2")
    assert call["content"]


def test_scan_by_path_sets_stream_header(client, transport):
    resp = client.scan_by_path("/mf/Document.docx")
    assert resp.verdict.value == "Benign"
    call = transport.calls[-1]
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert headers["stream-path"] == "/mf/Document.docx"


def test_scan_binary_without_token(monkeypatch, transport):
    httpx_client = httpx.Client(transport=transport)
    monkeypatch.setattr("dsxa_sdk.client.httpx.Client", lambda **kwargs: httpx_client)
    client = DSXAClient(base_url="https://scanner.example.com", auth_token=None)
    resp = client.scan_binary(b"data")
    assert resp.scan_guid == "guid-123"
    call = transport.calls[-1]
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert "authorization" not in headers
    client.close()


def test_default_protected_entity(monkeypatch, transport):
    httpx_client = httpx.Client(transport=transport)
    monkeypatch.setattr("dsxa_sdk.client.httpx.Client", lambda **kwargs: httpx_client)
    client = DSXAClient(base_url="https://scanner.example.com")
    client.scan_binary(b"data")
    call = transport.calls[-1]
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert headers["protected_entity"] == "1"
    client.close()


def test_poll_by_path_breaks_on_scanning(monkeypatch, client, transport):
    responses = [
        {"scan_guid": "guid-123", "verdict": "Scanning", "verdict_details": {"event_description": "in progress"}},
        {"scan_guid": "guid-123", "verdict": "Benign", "verdict_details": {"event_description": "done"}},
    ]

    def fake_request(self, method, path, **kwargs):
        payload = responses.pop(0)
        return payload

    monkeypatch.setattr("dsxa_sdk.client.DSXAClient._request", fake_request)
    resp = client.poll_scan_by_path("guid-123", interval_seconds=0.01, timeout_seconds=1)
    assert resp.verdict.value == "Benign"
