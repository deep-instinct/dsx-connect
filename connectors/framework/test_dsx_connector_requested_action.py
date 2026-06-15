import asyncio

from connectors.framework.base_config import BaseConnectorConfig
from connectors.framework.dsx_connector import (
    DSXConnector,
    DSXAConnectorRouter,
    apply_requested_action_config_update,
    resolve_item_action_request,
)
from shared.models.connector_models import ScanRequestModel, ItemActionEnum


class _JsonRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


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
