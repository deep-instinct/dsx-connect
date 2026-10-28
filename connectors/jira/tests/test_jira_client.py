import asyncio

import httpx
import pytest

from connectors.jira.config import JiraConnectorConfig
from connectors.jira.jira_client import JiraClient


def make_client(handler):
    return JiraClient(JiraConnectorConfig(
        jira_cloud_id="test-cloud", jira_email="test@example.com", jira_api_token="test-token",
        asset="key = TEST-1",
    ), transport=httpx.MockTransport(handler))


def test_paginated_discovery_deduplicates_and_preserves_jql():
    def handler(request):
        assert request.url.host == "api.atlassian.com"
        assert request.url.params['jql'] == 'key = TEST-1'
        assert request.headers['authorization'].startswith('Basic ')
        cursor = request.url.params.get('nextPageToken')
        return httpx.Response(200, json={
            'issues': [{'key': 'TEST-1', 'fields': {'attachment': [
                {'id': '1', 'filename': 'a.txt'},
                *([{'id': '2', 'filename': 'b.txt'}] if cursor else []),
            ]}}], 'isLast': bool(cursor), 'nextPageToken': None if cursor else 'next',
        })
    async def run():
        client = make_client(handler)
        try:
            assert [a['id'] async for _, a in client.attachments('key = TEST-1')] == ['1', '2']
        finally:
            await client.close()
    asyncio.run(run())


def test_download_stream_and_reject_untrusted_locations():
    def handler(request):
        assert request.url.path.endswith('/attachment/content/12')
        assert request.url.params['redirect'] == 'false'
        return httpx.Response(200, content=b'harmless')
    async def run():
        client = make_client(handler)
        try:
            with pytest.raises(ValueError):
                await client.open_attachment('https://untrusted.example/12')
            response = await client.open_attachment('12')
            assert await response.aread() == b'harmless'
            await response.aclose()
        finally:
            await client.close()
    asyncio.run(run())


def test_scope_failure_is_reported_without_token_or_response_body():
    async def run():
        client = make_client(lambda request: httpx.Response(401, text='sensitive response'))
        try:
            with pytest.raises(RuntimeError, match='Jira HTTP 401') as exc:
                await client.page('key = TEST-1')
            assert 'sensitive' not in str(exc.value)
            assert 'test-token' not in str(exc.value)
        finally:
            await client.close()
    asyncio.run(run())


def test_repeated_cursor_fails_instead_of_looping():
    async def run():
        client = make_client(lambda request: httpx.Response(200, json={'issues': [], 'nextPageToken': 'same'}))
        try:
            with pytest.raises(RuntimeError, match='repeated'):
                _ = [a async for a in client.attachments('key = TEST-1')]
        finally:
            await client.close()
    asyncio.run(run())


def test_download_does_not_follow_redirect_with_credentials():
    async def run():
        client = make_client(lambda request: httpx.Response(302, headers={'Location': 'https://untrusted.example'}))
        try:
            with pytest.raises(RuntimeError, match='302'):
                await client.open_attachment('12')
        finally:
            await client.close()
    asyncio.run(run())


def test_rate_limit_retries_with_retry_after(monkeypatch):
    calls = []
    delays = []
    async def sleep(delay):
        delays.append(delay)
    monkeypatch.setattr('connectors.jira.jira_client.asyncio.sleep', sleep)
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={'Retry-After': '2'})
        return httpx.Response(200, json={'issues': [], 'isLast': True})
    async def run():
        client = make_client(handler)
        try:
            assert await client.page('key = TEST-1') == ([], None)
            assert len(calls) == 2
            assert delays == [2.0]
        finally:
            await client.close()
    asyncio.run(run())


def test_demo_requires_nonempty_valid_allowlist():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        JiraConnectorConfig(jira_demo_mode=True)
    with pytest.raises(ValidationError):
        JiraConnectorConfig(jira_demo_mode=True, jira_demo_issue_keys=['TEST-1) OR project = RD'])


def test_demo_space_query_is_restricted_and_uses_real_project_name():
    def handler(request):
        assert 'key in (TEST-1)' in request.url.params['jql']
        assert request.url.params['fields'] == 'project'
        return httpx.Response(200, json={'isLast': True, 'issues': [
            {'key': 'TEST-1', 'fields': {'project': {'key': 'TEST', 'name': 'Demo space'}}},
            {'key': 'OTHER-1', 'fields': {'project': {'key': 'OTHER', 'name': 'Unapproved'}}},
        ]})
    async def run():
        client = make_client(handler)
        client.config.jira_demo_mode = True
        client.config.jira_demo_issue_keys = ['TEST-1']
        try:
            assert await client.demo_spaces() == [{'key': 'TEST', 'name': 'Demo space'}]
        finally:
            await client.close()
    asyncio.run(run())


def test_demo_download_rejects_attachment_outside_allowlist():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path.endswith('/search/jql')
        assert 'key in (TEST-1)' in request.url.params['jql']
        return httpx.Response(200, json={'isLast': True, 'issues': []})
    async def run():
        client = make_client(handler)
        client.config.jira_demo_mode = True
        client.config.jira_demo_issue_keys = ['TEST-1']
        try:
            with pytest.raises(ValueError, match='outside the demo'):
                await client.open_attachment('999')
            assert len(calls) == 1
        finally:
            await client.close()
    asyncio.run(run())


def test_demo_download_allows_only_approved_issue_attachments():
    def handler(request):
        if request.url.path.endswith('/search/jql'):
            assert 'key in (TEST-1)' in request.url.params['jql']
            return httpx.Response(200, json={'isLast': True, 'issues': [
                {'key': 'TEST-1', 'fields': {'attachment': [{'id': '12', 'filename': 'original.pdf'}]}},
            ]})
        assert request.url.path.endswith('/attachment/content/12')
        return httpx.Response(200, content=b'test')
    async def run():
        client = make_client(handler)
        client.config.jira_demo_mode = True
        client.config.jira_demo_issue_keys = ['TEST-1']
        try:
            response = await client.open_attachment('12')
            assert response.extensions['jira_filename'] == 'original.pdf'
            await response.aclose()
        finally:
            await client.close()
    asyncio.run(run())


def test_space_discovery_reads_project_metadata_only_and_paginates():
    def handler(request):
        assert request.method == 'GET'
        assert request.url.path.endswith('/project/search')
        assert request.url.params['startAt'] == '0'
        return httpx.Response(200, json={'values': [{'key': 'TEST', 'name': 'Test'}], 'total': 2, 'isLast': False})
    async def run():
        client = make_client(handler)
        try:
            values, cursor = await client.project_page(1)
            assert values[0]['key'] == 'TEST'
            assert cursor == '1'
        finally:
            await client.close()
    asyncio.run(run())
