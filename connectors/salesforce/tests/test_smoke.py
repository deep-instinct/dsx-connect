import asyncio

import pytest


@pytest.mark.asyncio
async def test_preview_provider_smoke():
    """
    Minimal smoke test to ensure preview provider returns a list.
    """
    from connectors.salesforce.salesforce_connector import connector  # type: ignore

    if connector.preview_provider is None:
        pytest.skip("No preview provider registered in template")

    items = await connector.preview_provider(3)
    assert isinstance(items, list)


def test_config_has_display_name():
    from connectors.salesforce.config import ConfigManager  # type: ignore

    cfg = ConfigManager.get_config()
    assert hasattr(cfg, "display_name")
    assert isinstance(cfg.display_name, str)


def test_salesforce_client_build_query_includes_asset():
    from connectors.salesforce.config import SalesforceConnectorConfig  # type: ignore
    from connectors.salesforce.salesforce_client import SalesforceClient  # type: ignore

    cfg = SalesforceConnectorConfig(
        sf_client_id="cid",
        sf_client_secret="secret",
        sf_username="user@example.com",
        sf_password="pass",
        asset="ContentDocumentId = '069xx0000001234AAA'",
    )
    client = SalesforceClient(cfg)
    query = client.build_query(limit=50)
    assert "ContentDocumentId = '069xx0000001234AAA'" in query
    assert "LIMIT 50" in query
    asyncio.run(client.close())


def test_webhook_extract_version_ids():
    from connectors.salesforce.salesforce_connector import _extract_version_ids  # type: ignore

    payload = {
        "records": [
            {"ContentVersionId": "068xx000000AAAAA"},
            {"VersionIds": ["068xx000000BBBBB", "068xx000000CCCCC"]},
        ]
    }
    ids = _extract_version_ids(payload)
    assert ids == ["068xx000000AAAAA", "068xx000000BBBBB", "068xx000000CCCCC"]


def test_include_record_respects_extensions(monkeypatch):
    from connectors.salesforce import salesforce_connector as module  # type: ignore

    monkeypatch.setattr(module.config, "filter", "pdf,docx")
    assert module._include_record({"FileExtension": "PDF"})
    assert not module._include_record({"FileExtension": "jpg"})
