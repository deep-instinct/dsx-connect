import asyncio

import pytest

from connectors.framework.base_config import BaseConnectorConfig
from connectors.framework.dsx_connector import (
    DSXConnector,
    DSXAConnectorRouter,
    apply_requested_action_config_update,
    resolve_item_action_request,
)
from shared.models.connector_models import ScanRequestModel, ItemActionEnum, ConnectorStatusEnum


class _JsonRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def connector_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("DSXCONNECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HOSTNAME", raising=False)
    monkeypatch.delenv("POD_UID", raising=False)


def test_put_config_applies_requested_action_to_legacy_item_action_fields() -> None:
    connector = DSXConnector(
        BaseConnectorConfig(
            name="test-connector",
            connector_url="http://127.0.0.1:9999",
            dsx_connect_url="http://127.0.0.1:8586",
        )
    )
    router = DSXAConnectorRouter(connector)

    result = asyncio.run(
        router.put_config(
            _JsonRequest(
                {
                    "requested_action": {
                        "type": "movetag",
                        "destination": {
                            "path": "tenant-quarantine",
                        },
                        "tags": {
                            "Verdict": "Malicious",
                        },
                    }
                }
            )
        )
    )

    assert result["item_action"] == "movetag"
    assert result["item_action_move_metainfo"] == "tenant-quarantine"
    assert connector.connector_running_model.item_action == "movetag"
    assert connector.connector_running_model.item_action_move_metainfo == "tenant-quarantine"
    assert connector.connector_config.item_action.value == "movetag"
    assert connector.connector_config.item_action_move_metainfo == "tenant-quarantine"


def test_apply_requested_action_config_update_updates_common_fields() -> None:
    connector = DSXConnector(
        BaseConnectorConfig(
            name="test-connector",
            connector_url="http://127.0.0.1:9999",
            dsx_connect_url="http://127.0.0.1:8586",
        )
    )

    changed = apply_requested_action_config_update(
        {
            "requested_action": {
                "type": "delete",
            }
        },
        connector_config=connector.connector_config,
        connector_running_model=connector.connector_running_model,
    )

    assert changed is True
    assert connector.connector_config.item_action.value == "delete"
    assert connector.connector_running_model.item_action == "delete"


def test_resolve_item_action_request_extracts_destination_filename_and_tags() -> None:
    resolved = resolve_item_action_request(
        ScanRequestModel(
            location="scan/eicar.txt",
            metainfo="scan/eicar.txt",
            requested_action={
                "type": "movetag",
                "destination": {
                    "path": "tenant-quarantine",
                    "filename": "eicar.txt_c23bbf85bc",
                },
                "tags": {
                    "Verdict": "Malicious",
                },
                "details": {
                    "quarantine_target": {
                        "preserve_relative_path": False,
                    }
                },
            },
        ),
        default_action=ItemActionEnum.NOTHING,
        default_target=None,
    )

    assert resolved.action == ItemActionEnum.MOVE_TAG
    assert resolved.target == "tenant-quarantine"
    assert resolved.filename == "eicar.txt_c23bbf85bc"
    assert resolved.tags == {"Verdict": "Malicious"}
    assert resolved.preserve_relative_path is False


def test_resolve_item_action_request_falls_back_to_defaults() -> None:
    resolved = resolve_item_action_request(
        ScanRequestModel(location="scan/eicar.txt", metainfo="scan/eicar.txt"),
        default_action=ItemActionEnum.MOVE_TAG,
        default_target="fallback-target",
        default_tags={"Verdict": "Malicious"},
    )

    assert resolved.action == ItemActionEnum.MOVE_TAG
    assert resolved.target == "fallback-target"
    assert resolved.filename is None
    assert resolved.tags == {"Verdict": "Malicious"}


def test_register_connector_returns_success_when_registration_disabled() -> None:
    connector = DSXConnector(
        BaseConnectorConfig(
            name="test-connector",
            connector_url="http://127.0.0.1:9999",
            dsx_connect_url="http://127.0.0.1:8091",
            register_with_core=False,
        )
    )

    result = asyncio.run(connector.register_connector(connector.connector_running_model))

    assert result.status.value == "success"
    assert result.message == "Registration disabled"


def test_unregister_connector_returns_success_when_registration_disabled() -> None:
    connector = DSXConnector(
        BaseConnectorConfig(
            name="test-connector",
            connector_url="http://127.0.0.1:9999",
            dsx_connect_url="http://127.0.0.1:8091",
            register_with_core=False,
        )
    )

    result = asyncio.run(connector.unregister_connector())

    assert result.status.value == "success"
    assert result.message == "Unregistration disabled"


def test_ng_registration_payload_uses_runtime_identity_and_capabilities() -> None:
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            instance_id="gcs-pod-1",
            ng_platform_key="project-a",
            ng_connector_labels={"namespace": "dsx-connect"},
        )
    )

    async def read_file(_request):
        return None

    async def discover_assets():
        return None

    connector.read_file(read_file)
    connector.asset_discovery(discover_assets)

    payload = connector._ng_registration_payload()

    assert payload["connector_instance_id"] == "gcs-pod-1"
    assert payload["platform"] == "gcs"
    assert payload["platform_key"] == "project-a"
    assert payload["connector_name"] == "google-cloud-storage-connector"
    assert payload["base_url"] == "http://gcs/google-cloud-storage-connector"
    assert payload["capabilities"]["discover"] is True
    assert payload["capabilities"]["read"] is True
    assert payload["capabilities"]["write"] is False
    assert payload["labels"] == {"namespace": "dsx-connect"}


def test_ng_heartbeat_falls_back_to_register_when_instance_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = str(self._payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected status {self.status_code}")

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json or {}))
            if url.endswith("/heartbeat"):
                return _FakeResponse(404)
            return _FakeResponse(200, {"connector_instance_id": "gcs-pod-1"})

    from connectors.framework import dsx_connector as connector_module

    monkeypatch.setattr(connector_module.httpx, "AsyncClient", _FakeAsyncClient)
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            instance_id="gcs-pod-1",
            ng_platform_key="project-a",
        )
    )

    result = asyncio.run(connector.heartbeat_ng_control_plane())

    assert result.status.value == "success"
    assert "/api/v1/control-plane/connectors/" in calls[0][1]
    assert "/dsx-connect/api/v1/" not in calls[0][1]
    assert calls[0][1].endswith("/api/v1/control-plane/connectors/gcs-pod-1/heartbeat")
    assert calls[1][1].endswith("/api/v1/control-plane/connectors/register")
    assert "/dsx-connect/api/v1/" not in calls[1][1]


def test_ng_only_scan_request_uses_execution_batch_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _FakeResponse:
        content = b"{}"

        def json(self):
            return {"job_id": "job_monitor_1"}

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, json or {}))
            return _FakeResponse()

    from connectors.framework import dsx_connector as connector_module

    monkeypatch.setattr(connector_module.httpx, "AsyncClient", _FakeAsyncClient)
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            ng_integration_id="int_gcs",
            instance_id="gcs-pod-1",
        )
    )
    connector.connector_running_model.status = ConnectorStatusEnum.READY

    result = asyncio.run(
        connector.scan_file_request(
            ScanRequestModel(location="incoming/file.pdf", metainfo="lg-test-01/incoming/file.pdf")
        )
    )

    assert result.status.value == "success"
    assert calls[0][0].endswith("/api/v1/execution/jobs/batch")
    assert "/dsx-connect/api/v1/" not in calls[0][0]
    assert calls[0][1]["integration_id"] == "int_gcs"
    assert calls[0][1]["payload"]["source"] == "connector"
    assert calls[0][1]["payload"]["deferPublish"] is True
    assert calls[0][1]["items"] == [
        {
            "object_identity": "lg-test-01/incoming/file.pdf",
            "payload": {
                "readerStrategy": "proxy",
                "location": "incoming/file.pdf",
                "path": "incoming/file.pdf",
                "metainfo": "lg-test-01/incoming/file.pdf",
            },
        }
    ]


def test_ng_registration_response_sets_scan_integration_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _FakeResponse:
        content = b"{}"

        def __init__(self, payload: dict):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, json or {}))
            if url.endswith("/control-plane/connectors/register"):
                return _FakeResponse({"connector_instance_id": "gcs-pod-1", "integration_id": "int_from_register"})
            return _FakeResponse({"job_id": "job_monitor_1"})

    from connectors.framework import dsx_connector as connector_module

    monkeypatch.setattr(connector_module.httpx, "AsyncClient", _FakeAsyncClient)
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            instance_id="gcs-pod-1",
        )
    )
    connector.connector_running_model.status = ConnectorStatusEnum.READY

    register_result = asyncio.run(connector.register_ng_control_plane())
    scan_result = asyncio.run(
        connector.scan_file_request(
            ScanRequestModel(location="incoming/file.pdf", metainfo="lg-test-01/incoming/file.pdf")
        )
    )

    assert register_result.status.value == "success"
    assert scan_result.status.value == "success"
    assert calls[1][1]["integration_id"] == "int_from_register"


def test_ng_only_batch_scan_request_uses_execution_batch_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _FakeResponse:
        content = b"{}"

        def json(self):
            return {"job_id": "job_batch_1"}

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, json or {}))
            return _FakeResponse()

    from connectors.framework import dsx_connector as connector_module

    monkeypatch.setattr(connector_module.httpx, "AsyncClient", _FakeAsyncClient)
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            ng_integration_id="int_gcs",
            instance_id="gcs-pod-1",
        )
    )
    connector.connector_running_model.status = ConnectorStatusEnum.READY

    result = asyncio.run(
        connector.scan_file_request_batch(
            [
                ScanRequestModel(location="incoming/a.pdf", metainfo="lg-test-01/incoming/a.pdf"),
                ScanRequestModel(location="incoming/b.pdf", metainfo="lg-test-01/incoming/b.pdf"),
            ]
        )
    )

    assert result.status.value == "success"
    assert calls[0][0].endswith("/api/v1/execution/jobs/batch")
    assert calls[0][1]["integration_id"] == "int_gcs"
    assert calls[0][1]["payload"]["itemCount"] == 2
    assert [item["object_identity"] for item in calls[0][1]["items"]] == [
        "lg-test-01/incoming/a.pdf",
        "lg-test-01/incoming/b.pdf",
    ]
    assert {item["payload"]["readerStrategy"] for item in calls[0][1]["items"]} == {"proxy"}


def test_ng_only_batch_scan_request_preserves_scan_source_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    class _FakeResponse:
        content = b"{}"

        def json(self):
            return {"job_id": "job_batch_1"}

        def raise_for_status(self):
            return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append((url, json or {}))
            return _FakeResponse()

    from connectors.framework import dsx_connector as connector_module

    monkeypatch.setattr(connector_module.httpx, "AsyncClient", _FakeAsyncClient)
    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            ng_integration_id="int_gcs",
            instance_id="gcs-pod-1",
        )
    )
    connector.connector_running_model.status = ConnectorStatusEnum.READY

    result = asyncio.run(
        connector.scan_file_request_batch(
            [
                ScanRequestModel(
                    location="incoming/a.pdf",
                    metainfo="lg-test-01/incoming/a.pdf",
                    scan_source="connector_monitor",
                ),
            ]
        )
    )

    assert result.status.value == "success"
    assert calls[0][1]["payload"]["source"] == "connector_monitor"


def test_ng_only_connector_does_not_create_legacy_uuid_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSXCONNECTOR_DATA_DIR", str(tmp_path))

    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect-ng:8091",
            register_with_core=False,
            register_with_ng_control_plane=True,
            instance_id="gcs-pod-1",
            ng_platform_key="project-a",
        )
    )

    assert connector.connector_instance_id == "gcs-pod-1"
    assert not (tmp_path / "connector_uuid.txt").exists()


def test_legacy_registration_still_creates_stable_uuid_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSXCONNECTOR_DATA_DIR", str(tmp_path))

    connector = DSXConnector(
        BaseConnectorConfig(
            name="google-cloud-storage-connector",
            connector_url="http://gcs:80",
            dsx_connect_url="http://dsx-connect:8586",
            register_with_core=True,
            register_with_ng_control_plane=False,
        )
    )

    assert str(connector.connector_running_model.uuid) == (tmp_path / "connector_uuid.txt").read_text().strip()
