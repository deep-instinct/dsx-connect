from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from dsx_connect_v2.control_plane.discovery_settings import DiscoverySettings, discovery_due


def test_requests_override_cooldown_and_retry_while_periodic_is_paused():
    now = datetime.now(timezone.utc)
    config = DiscoverySettings(periodic_enabled=False)
    status = dict(state='complete', last_attempt_at=now, active_request_id='old')
    assert not discovery_due(None, None, config, now)
    request = dict(request_id='new', completed_at=None)
    assert discovery_due(status, request, config, now)
    status.update(state='error', active_request_id='new', consecutive_failures=2)
    assert not discovery_due(status, request, config, now + timedelta(seconds=119))
    assert discovery_due(status, request, config, now + timedelta(seconds=120))
    status['consecutive_failures'] = 9999
    assert discovery_due(status, request, config, now + timedelta(seconds=900))
    request['completed_at'] = now
    assert not discovery_due(status, request, config, now + timedelta(days=1))


def test_policy_rejects_unbounded_work_and_invalid_backoff():
    for values in [dict(concurrency=0), dict(concurrency=17), dict(interval_seconds=1),
                   dict(max_pages_per_pass=101), dict(request_timeout_seconds=61),
                   dict(retry_initial_seconds=100, retry_max_seconds=50)]:
        with pytest.raises(ValidationError):
            DiscoverySettings(**values)


def test_slow_connector_does_not_block_coordinator_or_other_connectors(monkeypatch):
    import asyncio
    import threading
    from types import SimpleNamespace
    from dsx_connect_v2.workers import discovery_worker as worker

    release = threading.Event()
    slow_started = threading.Event()
    completed = []
    heartbeats = []
    rows = [SimpleNamespace(integration_id=key) for key in ['slow', 'fast', 'next']]
    class Store:
        def heartbeat(self, _, active):
            heartbeats.append(active)
        def settings(self):
            return {'settings': DiscoverySettings(concurrency=2).model_dump()}
        def due_integrations(self, integrations, config):
            return [row for row in integrations if row.integration_id not in completed]
    def refresh(_, row, *args):
        if row.integration_id == 'slow':
            slow_started.set()
            assert release.wait(2)
        completed.append(row.integration_id)
    monkeypatch.setattr(worker, '_refresh_one', refresh)
    monkeypatch.setattr(worker, 'POLL_SECONDS', .01)
    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(worker.serve(SimpleNamespace(list_integrations=lambda: rows), Store(), stop=stop))
        try:
            async with asyncio.timeout(2):
                while 'next' not in completed:
                    await asyncio.sleep(.01)
            assert slow_started.is_set() and 'slow' not in completed
            assert max(heartbeats) <= 2
        finally:
            release.set()
            stop.set()
            await task
    asyncio.run(scenario())
