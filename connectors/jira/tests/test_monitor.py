import asyncio
from types import SimpleNamespace

import pytest

from connectors.jira.monitor import Checkpoints, JiraMonitor

SCOPE = {'scope_id': 'scope-demo', 'resource_selector': 'project = TEST'}


class Client:
    config = SimpleNamespace(asset='')
    cloud_id = 'cloud'

    def __init__(self):
        self.items = [('TEST-1', {'id': '1', 'filename': 'old.pdf', 'size': 12})]
        self.fail = False

    async def attachments(self, jql):
        assert jql == 'project = TEST'
        for item in self.items:
            yield item
        if self.fail:
            raise RuntimeError('search failed')


def test_first_poll_baselines_then_only_new_attachments_submit(tmp_path):
    async def run():
        state = Checkpoints(tmp_path / 'state.db')
        client = Client()
        submitted = []
        async def submit(payload):
            submitted.append(payload)
        monitor = JiraMonitor(client, state, lambda a: True, submit)
        assert await monitor.poll_scope('integration', SCOPE) == {'baseline': 1, 'submitted': 0}
        client.items.append(('TEST-1', {'id': '2', 'filename': 'new.pdf', 'size': 20}))
        assert (await monitor.poll_scope('integration', SCOPE))['submitted'] == 1
        assert (await monitor.poll_scope('integration', SCOPE))['submitted'] == 0
        assert len(submitted) == 1
        payload = submitted[0]
        assert payload['scope_id'] == 'scope-demo'
        assert payload['payload']['scanOnly'] is True
        assert payload['items'][0]['payload']['attribution']['file_name'] == 'new.pdf'
        assert payload['items'][0]['payload']['path'] == '2'
        state.close()
        state = Checkpoints(tmp_path / 'state.db')
        assert (await JiraMonitor(client, state, lambda a: True, submit).poll_scope('integration', SCOPE))['submitted'] == 0
        state.close()
    asyncio.run(run())


def test_failed_submission_retries_same_idempotency_key(tmp_path):
    async def run():
        state = Checkpoints(tmp_path / 'state.db')
        client = Client()
        attempts = []
        async def submit(payload):
            attempts.append(payload)
            if len(attempts) == 1:
                raise RuntimeError('ambiguous timeout')
        monitor = JiraMonitor(client, state, lambda a: True, submit)
        await monitor.poll_scope('integration', SCOPE)
        client.items.append(('TEST-1', {'id': '2', 'filename': 'new.pdf'}))
        with pytest.raises(RuntimeError):
            await monitor.poll_scope('integration', SCOPE)
        assert (await monitor.poll_scope('integration', SCOPE))['submitted'] == 1
        assert attempts[0]['idempotency_key'] == attempts[1]['idempotency_key']
        state.close()
    asyncio.run(run())


def test_partial_discovery_does_not_commit_baseline(tmp_path):
    async def run():
        state = Checkpoints(tmp_path / 'state.db')
        client = Client()
        client.fail = True
        async def submit(payload):
            pytest.fail('baseline must not submit')
        monitor = JiraMonitor(client, state, lambda a: True, submit)
        with pytest.raises(RuntimeError):
            await monitor.poll_scope('integration', SCOPE)
        assert not state.initialized('cloud:integration')
        client.fail = False
        assert (await monitor.poll_scope('integration', SCOPE))['baseline'] == 1
        state.close()
    asyncio.run(run())


def test_filtered_attachments_are_not_queued(tmp_path):
    async def run():
        state = Checkpoints(tmp_path / 'state.db')
        client = Client()
        async def submit(payload):
            pytest.fail('excluded file must not submit')
        monitor = JiraMonitor(client, state, lambda a: a['filename'].endswith('.txt'), submit)
        await monitor.poll_scope('integration', SCOPE)
        client.items.append(('TEST-1', {'id': '2', 'filename': 'excluded.pdf'}))
        assert (await monitor.poll_scope('integration', SCOPE))['submitted'] == 0
        state.close()
    asyncio.run(run())


def test_overlapping_scopes_do_not_submit_same_attachment_twice(tmp_path):
    async def run():
        state = Checkpoints(tmp_path / 'state.db')
        client = Client()
        submitted = []
        async def submit(payload):
            submitted.append(payload)
        monitor = JiraMonitor(client, state, lambda a: True, submit)
        await monitor.poll_scope('integration', SCOPE)
        client.items.append(('TEST-1', {'id': '2', 'filename': 'new.pdf'}))
        await monitor.poll_scope('integration', SCOPE)
        await monitor.poll_scope('integration', {**SCOPE, 'scope_id': 'overlap'})
        assert len(submitted) == 1
        state.close()
    asyncio.run(run())
