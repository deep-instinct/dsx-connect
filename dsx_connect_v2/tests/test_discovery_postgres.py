"""Durable queue, online triggers, concurrency locks and audit integration tests."""
import os
import uuid
from types import SimpleNamespace

import pytest

from dsx_connect_v2.control_plane.coverage_inventory import _refresh_one
from dsx_connect_v2.control_plane.discovery_settings import DiscoverySettings, DiscoverySettingsStore
from dsx_connect_v2.jobs.postgres_repo import apply_schema

psycopg = pytest.importorskip('psycopg')
URL = os.getenv('DSX_CONNECT_V2_TEST_POSTGRES_URL')
pytestmark = pytest.mark.skipif(not URL, reason='requires a dedicated PostgreSQL test database')


@pytest.fixture
def discovery():
    apply_schema(URL)
    key = 'discovery-' + uuid.uuid4().hex
    store = DiscoverySettingsStore(URL)
    original = store.settings()
    with store._connect() as conn:
        conn.execute("INSERT INTO cp_integrations(integration_id, platform, platform_key, display_name, capability_discover) VALUES (%s,'s3',%s,'Discovery test',TRUE)", (key,key))
    try:
        yield store, SimpleNamespace(integration_id=key, enabled=True, capability_discover=True)
    finally:
        latest = store.settings()
        store.save_settings(DiscoverySettings(**original['settings']), latest['revision'])
        with store._connect() as conn:
            conn.execute('DELETE FROM cp_integrations WHERE integration_id=%s', (key,))


def test_policy_audits_changes_and_detects_stale_edits(discovery):
    store, _ = discovery
    original = store.settings()
    config = DiscoverySettings(**{**original['settings'], 'concurrency': 3})
    changed = store.save_settings(config, original['revision'])
    assert changed['revision'] == original['revision'] + 1
    assert store.save_settings(config, changed['revision'])['revision'] == changed['revision']
    with pytest.raises(ValueError, match='changed'):
        store.save_settings(config, original['revision'])
    with store._connect() as conn:
        audit = conn.execute('SELECT * FROM cp_discovery_settings_audit WHERE revision=%s ORDER BY event_id DESC LIMIT 1', (changed['revision'],)).fetchone()
        assert audit['settings']['concurrency'] == 3
        assert audit['previous_settings'] == original['settings']


def test_online_trigger_queues_first_online_and_expired_reconnect_only(discovery):
    store, row = discovery
    key = row.integration_id
    with store._connect() as conn:
        conn.execute("INSERT INTO cp_connector_instances(connector_instance_id,integration_id,platform,platform_key,connector_name,base_url) VALUES (%s,%s,'s3',%s,'test','http://unused')", (key,key,key))
    first = next(r for r in store.status()['inventory'] if r['integration_id'] == key)
    assert first['reason'] == 'connector_online'
    with store._connect() as conn:
        conn.execute('UPDATE cp_connector_instances SET last_seen_at=clock_timestamp() WHERE connector_instance_id=%s', (key,))
    assert next(r for r in store.status()['inventory'] if r['integration_id'] == key)['request_id'] == first['request_id']
    with store._connect() as conn:
        conn.execute("UPDATE cp_connector_instances SET expires_at=clock_timestamp()-INTERVAL '1 second' WHERE connector_instance_id=%s", (key,))
        conn.execute("UPDATE cp_connector_instances SET last_seen_at=clock_timestamp(), expires_at=clock_timestamp()+INTERVAL '120 seconds' WHERE connector_instance_id=%s", (key,))
    assert next(r for r in store.status()['inventory'] if r['integration_id'] == key)['request_id'] != first['request_id']


def test_newer_request_survives_older_completion_and_lock_prevents_duplicates(discovery):
    store, row = discovery
    old = store.request([row.integration_id])[0]['request_id']
    new = []
    def discover(_, cursor):
        # This separate connection must fail to acquire the current refresh lock.
        _refresh_one(store, row, lambda *_: pytest.fail('duplicate refresh'))
        new.append(store.request([row.integration_id])[0]['request_id'])
        return {'assets':[{'selector':'one'}]}, 'bucket'
    _refresh_one(store, row, discover)
    with store._connect() as conn:
        queued = conn.execute('SELECT * FROM cp_discovery_refresh_queue WHERE integration_id=%s', (row.integration_id,)).fetchone()
        assert queued['request_id'] == new[0] and queued['completed_at'] is None
        assert conn.execute('SELECT outcome FROM cp_discovery_refresh_audit WHERE request_id=%s', (old,)).fetchone()['outcome'] == 'superseded'
    _refresh_one(store, row, lambda *_: ({'assets':[{'selector':'two'}]}, 'bucket'))
    with store._connect() as conn:
        assert conn.execute('SELECT outcome FROM cp_discovery_refresh_queue WHERE integration_id=%s', (row.integration_id,)).fetchone()['outcome'] == 'complete'


def test_paged_request_resumes_after_restart_even_when_periodic_paused(discovery):
    store, row = discovery
    config = DiscoverySettings(periodic_enabled=False, max_pages_per_pass=1)
    store.request([row.integration_id])
    _refresh_one(store, row, lambda *_: ({'assets':[{'selector':'one'}], 'next_cursor':'page2'},'bucket'), config)
    with store._connect() as conn:
        status = conn.execute('SELECT * FROM cp_asset_inventory_status WHERE integration_id=%s', (row.integration_id,)).fetchone()
        assert status['state'] == 'partial' and status['next_cursor'] == 'page2'
        conn.execute("UPDATE cp_asset_inventory_status SET last_attempt_at=clock_timestamp()-INTERVAL '6 seconds' WHERE integration_id=%s", (row.integration_id,))
    restarted = DiscoverySettingsStore(URL)
    def finish(_, cursor):
        assert cursor == 'page2'
        return {'assets':[{'selector':'two'}]}, 'bucket'
    _refresh_one(restarted, row, finish, config)
    assert restarted.history(7,row.integration_id)['current']['discovered'] == 2
    with restarted._connect() as conn:
        assert conn.execute('SELECT completed_at FROM cp_discovery_refresh_queue WHERE integration_id=%s', (row.integration_id,)).fetchone()['completed_at'] is not None
