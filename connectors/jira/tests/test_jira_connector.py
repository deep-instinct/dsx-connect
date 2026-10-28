import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from connectors.jira import jira_connector as jira
from shared.models.connector_models import ScanRequestModel
from shared.models.status_responses import StatusResponse, StatusResponseEnum


def test_listing_limit_and_cursor_do_not_drop_attachments(monkeypatch):
    page = AsyncMock(return_value=([{'key': 'TEST-1', 'fields': {'attachment': [
        {'id': str(i), 'filename': f'{i}.txt', 'size': 5} for i in range(3)
    ]}}], None))
    monkeypatch.setattr(jira, 'client', SimpleNamespace(page=page, cloud_id='cloud'))
    monkeypatch.setattr(jira.config, 'asset', 'key = TEST-1')
    async def run():
        first = await jira.object_listing(limit=2)
        second = await jira.object_listing(limit=2, cursor=first.next_cursor)
        assert [x.location for x in first.objects + second.objects] == ['0', '1', '2']
        assert second.next_cursor is None
    asyncio.run(run())


def test_full_scan_reports_enqueue_failure(monkeypatch):
    async def attachments(scope):
        yield 'TEST-1', {'id': '1', 'filename': 'a.txt', 'size': 3}
    monkeypatch.setattr(jira, 'client', SimpleNamespace(attachments=attachments))
    enqueue = AsyncMock(return_value=StatusResponse(status=StatusResponseEnum.ERROR, message='unreachable'))
    monkeypatch.setattr(jira.connector, 'scan_file_request', enqueue)
    result = asyncio.run(jira.full_scan())
    assert result.status == StatusResponseEnum.ERROR
    assert 'after 0' in result.message


def test_read_reports_error_before_streaming(monkeypatch):
    monkeypatch.setattr(jira, 'client', SimpleNamespace(open_attachment=AsyncMock(side_effect=RuntimeError('Jira HTTP 403'))))
    result = asyncio.run(jira.read_file(ScanRequestModel(location='1', metainfo='a.txt')))
    assert result.status == StatusResponseEnum.ERROR


def test_asset_discovery_http_route_matches_framework_contract(monkeypatch):
    import httpx
    from connectors.framework.dsx_connector import connector_api
    monkeypatch.setattr(jira.config, 'asset', 'key = TEST-1')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=connector_api), base_url='http://test') as client:
            response = await client.get('/jira-connector/assets', params={'type': 'bucket', 'source': 'all', 'limit': 100})
            assert response.status_code == 200
            body = response.json()
            assert body['asset_type'] == 'jira_jql'
            assert body['assets'][0]['selector'] == 'key = TEST-1'
            response = await client.get('/jira-connector/assets', params={'asset_filter_mode': 'contains', 'asset_filter_value': 'unrelated'})
            assert response.json()['assets'] == []
    asyncio.run(run())


def test_demo_discovery_exposes_space_and_selected_issues(monkeypatch):
    monkeypatch.setattr(jira.config, 'jira_demo_mode', True)
    monkeypatch.setattr(jira.config, 'jira_demo_issue_keys', ['TEST-1'])
    monkeypatch.setattr(jira, 'client', SimpleNamespace(demo_spaces=AsyncMock(return_value=[{'key': 'TEST', 'name': 'Test space'}])))
    result = asyncio.run(jira.asset_discovery('bucket', 'all', 100))
    assert result.asset_type == 'jira_space'
    assert result.assets[0].selector == 'project = "TEST"'
    assert 'Selected issues: TEST-1' in result.assets[0].display_name
    assert result.assets[0].metadata['allowed_issue_keys'] == ['TEST-1']


def test_all_spaces_visible_but_unapproved_spaces_labeled_disabled(monkeypatch):
    monkeypatch.setattr(jira.config, 'jira_discover_spaces', True)
    monkeypatch.setattr(jira.config, 'jira_demo_mode', True)
    monkeypatch.setattr(jira.config, 'jira_demo_issue_keys', ['TEST-1'])
    monkeypatch.setattr(jira, 'client', SimpleNamespace(project_page=AsyncMock(return_value=([
        {'key': 'TEST', 'name': 'Test space'}, {'key': 'OTHER', 'name': 'Other space'},
    ], '2'))))
    result = asyncio.run(jira.asset_discovery('bucket', 'all', 2))
    assert len(result.assets) == 2
    assert result.next_cursor == '2'
    assert result.assets[0].metadata['allowed_issue_keys'] == ['TEST-1']
    assert 'Demo scans disabled' in result.assets[1].display_name
    assert result.assets[1].metadata['demo_scans_enabled'] is False
