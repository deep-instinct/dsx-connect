"""Real transactional trigger checks using an explicitly configured test database."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from dsx_connect_v2.jobs.postgres_repo import apply_schema
from dsx_connect_v2.control_plane.coverage import ProtectionCoverageStore
from dsx_connect_v2.control_plane.coverage_inventory import store_page, _refresh_one

psycopg = pytest.importorskip('psycopg')
URL = os.getenv('DSX_CONNECT_V2_TEST_POSTGRES_URL')
pytestmark = pytest.mark.skipif(not URL, reason='requires a dedicated PostgreSQL test database')


def test_audit_is_transactional_deduplicated_filterable_and_retained_after_deletion():
    apply_schema(URL)
    suffix = uuid.uuid4().hex
    integration, scope = 'coverage-i-' + suffix, 'coverage-s-' + suffix
    store = ProtectionCoverageStore(URL)
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("INSERT INTO cp_integrations(integration_id, platform, platform_key, display_name) VALUES (%s, 's3', %s, 'Audit test')", (integration, suffix))
        conn.execute("INSERT INTO cp_scopes(scope_id, integration_id, scope_type, resource_selector, normalized_selector, display_name, mode) VALUES (%s, %s, 'identity', 'test-bucket', 'test-bucket', 'Audit bucket', 'monitor')", (scope, integration))
        store_page(conn, integration, 'bucket', [dict(selector='test-bucket', display_name='Audit bucket')])
        assert store.protected_count([integration]) == store.history(7, integration)['current']['protected'] == 1
        assert store.protected_count([]) == 0
        assert store.asset_counts([integration]) == {'discovered': 1, 'protected': 1}
        revision = store.revision(integration)
        assert revision > 0
        with pytest.raises(RuntimeError):
            with conn.transaction():
                conn.execute('UPDATE cp_scopes SET enabled = FALSE WHERE scope_id = %s', (scope,))
                raise RuntimeError('rollback')
        assert store.revision(integration) == revision
        conn.execute('UPDATE cp_integrations SET config_json = %s::jsonb WHERE integration_id = %s', ('{"secret": "must-not-be-audited"}', integration))
        assert store.revision(integration) == revision
        conn.execute("INSERT INTO cp_scan_schedules(scope_id, enabled, frequency, local_time, timezone) VALUES (%s, TRUE, 'daily', '12:00', 'UTC')", (scope,))
        scheduled_revision = store.revision(integration)
        assert scheduled_revision > revision
        conn.execute("UPDATE cp_scan_schedules SET last_outcome = 'submitted', next_run_at = NOW() WHERE scope_id = %s", (scope,))
        assert store.revision(integration) == scheduled_revision
        data = store.history(7, integration)
        assert data['current']['monitoring'] == data['current']['scheduled'] == 1
        assert any('Scheduled scan granted' in note for change in data['changes'] for note in change['notes'])
        assert store.history(7, 'nonexistent-integration')['current']['total'] == 0
        conn.execute('UPDATE cp_integrations SET enabled = FALSE WHERE integration_id = %s', (integration,))
        with conn.transaction():
            before = conn.execute('SELECT clock_timestamp()').fetchone()[0]
            conn.execute('UPDATE cp_scopes SET display_name = %s WHERE scope_id = %s', ('Renamed audit bucket', scope))
            recorded = conn.execute('SELECT occurred_at FROM cp_protection_events WHERE entity_id = %s ORDER BY event_id DESC LIMIT 1', (scope,)).fetchone()[0]
            assert recorded >= before
        data = store.history(7, integration)
        assert data['current']['unprotected'] == 1
        assert store.protected_count([integration]) == data['current']['protected'] == 0
        assert store.asset_counts([integration]) == {'discovered': 1, 'protected': 0}
        assert any('Monitoring removed' in note for change in data['changes'] for note in change['notes'])
        epoch = data['recording_started_at']
        revision = store.revision(integration)
        apply_schema(URL)
        assert store.revision(integration) == revision
        assert store.history(7, integration)['recording_started_at'] == epoch
        conn.execute('DELETE FROM cp_integrations WHERE integration_id = %s', (integration,))
        assert store.history(7, integration)['current']['total'] == 1
        assert store.history(7, integration)['current']['unprotected'] == 1
        events = conn.execute('SELECT state FROM cp_protection_events WHERE integration_id = %s', (integration,)).fetchall()
        assert events
        assert all('secret' not in str(row[0]) for row in events)


def test_existing_configuration_gets_an_honest_baseline_not_backdated_history():
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from dsx_connect_v2.jobs.postgres_repo import migration_files

    schema = 'coverage_baseline_' + uuid.uuid4().hex
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    isolated_url = make_conninfo(URL, options=f'-csearch_path={schema}')
    try:
        with psycopg.connect(isolated_url) as conn:
            for migration in migration_files():
                if migration.name < '0016':
                    conn.execute(migration.read_text())
            conn.execute("INSERT INTO cp_integrations(integration_id, platform, platform_key, display_name, created_at) VALUES ('i', 's3', 'key', 'Existing', NOW() - INTERVAL '30 days')")
            conn.execute("INSERT INTO cp_scopes(scope_id, integration_id, scope_type, resource_selector, normalized_selector, display_name, mode) VALUES ('s', 'i', 'identity', 'bucket', 'bucket', 'Existing bucket', 'full_scan')")
            conn.execute("INSERT INTO cp_scan_schedules(scope_id, enabled, frequency, local_time, timezone) VALUES ('s', TRUE, 'daily', '12:00', 'UTC')")
        apply_schema(isolated_url)
        store = ProtectionCoverageStore(isolated_url)
        data = store.history(7)
        assert data['current']['discovered'] == 0
        assert data['current']['known'] == data['current']['protected'] == 1
        assert store.protected_count(['i']) == 1
        assert store.asset_counts(['i']) == {'discovered': 0, 'protected': 1}
        assert data['changes'] == []
        assert data['series'][0]['scheduled'] is None
        assert data['series'][1]['notes'] == ['Recording started: current configuration baseline.']
        first_epoch = data['recording_started_at']
        apply_schema(isolated_url)
        assert store.history(7)['recording_started_at'] == first_epoch
        with psycopg.connect(isolated_url) as conn:
            assert conn.execute('SELECT count(*) FROM cp_protection_events').fetchone()[0] == 4
            store_page(conn, 'i', 'bucket', [dict(selector='bucket', display_name='Existing bucket')])
        data = store.history(7)
        assert data['current']['discovered'] == data['current']['protected'] == data['current']['scheduled'] == 1
        assert data['changes'][-1]['notes'] == ['Existing bucket: discovery confirmed']
    finally:
        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_inventory_partial_and_failed_walks_preserve_assets_and_complete_walk_removes_only_missing():
    from types import SimpleNamespace

    apply_schema(URL)
    suffix = uuid.uuid4().hex
    integration = 'inventory-' + suffix
    store = ProtectionCoverageStore(URL)
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("INSERT INTO cp_integrations(integration_id, platform, platform_key, display_name) VALUES (%s, 's3', %s, 'Inventory test')", (integration, suffix))
        store_page(conn, integration, 'bucket', [dict(selector='old')])
        conn.execute("UPDATE cp_discovered_assets SET last_seen_at = NOW() - INTERVAL '1 day' WHERE integration_id = %s", (integration,))
    record = SimpleNamespace(integration_id=integration, enabled=True, capability_discover=True)
    calls = []
    def failed_second_page(_, cursor):
        calls.append(cursor)
        if cursor is None:
            return dict(status='success', source='all', assets=[dict(selector='first')], nextCursor='page2'), 'bucket'
        return dict(status='permission_denied', source='all', assets=[]), 'bucket'
    _refresh_one(store, record, failed_second_page)
    assert calls == [None, 'page2']
    assert store.history(7, integration)['current']['discovered'] == 2
    with psycopg.connect(URL, autocommit=True) as conn:
        status = conn.execute('SELECT state, next_cursor FROM cp_asset_inventory_status WHERE integration_id = %s', (integration,)).fetchone()
        assert status == ('error', 'page2')
        conn.execute("UPDATE cp_asset_inventory_status SET last_attempt_at = NOW() - INTERVAL '2 minutes' WHERE integration_id = %s", (integration,))
    def finish(_, cursor):
        assert cursor == 'page2'
        return dict(status='success', source='all', assets=[dict(selector='second')]), 'bucket'
    _refresh_one(store, record, finish)
    data = store.history(7, integration)
    assert data['current']['discovered'] == data['current']['unprotected'] == 2
    assert any('old: removed from discovered inventory' in note for change in data['changes'] for note in change['notes'])
    with psycopg.connect(URL, autocommit=True) as conn:
        names = conn.execute('SELECT selector FROM cp_discovered_assets WHERE integration_id = %s AND active ORDER BY selector', (integration,)).fetchall()
        assert names == [('first',), ('second',)]
        assert conn.execute('SELECT state FROM cp_asset_inventory_status WHERE integration_id = %s', (integration,)).fetchone()[0] == 'complete'
        conn.execute('DELETE FROM cp_integrations WHERE integration_id = %s', (integration,))


def test_snapshot_queries_latest_audit_state_at_the_selected_time():
    apply_schema(URL)
    suffix = uuid.uuid4().hex
    integration, scope = 'snapshot-i-' + suffix, 'snapshot-s-' + suffix
    store = ProtectionCoverageStore(URL)
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("INSERT INTO cp_integrations(integration_id, platform, platform_key, display_name) VALUES (%s, 's3', %s, 'Snapshot test')", (integration, suffix))
        conn.execute("INSERT INTO cp_scopes(scope_id, integration_id, scope_type, resource_selector, normalized_selector, display_name, mode) VALUES (%s, %s, 'identity', 'bucket', 'bucket', 'Historical bucket', 'full_scan')", (scope, integration))
        store_page(conn, integration, 'bucket', [dict(selector='bucket', display_name='Historical bucket')])
        selected = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        conn.execute('UPDATE cp_scopes SET enabled = FALSE WHERE scope_id = %s', (scope,))
        store_page(conn, integration, 'bucket', [dict(selector='later')])
        snapshot = store.snapshot(selected, integration)
        assert snapshot['counts']['discovered'] == snapshot['counts']['protected'] == 1
        assert snapshot['assets'][0]['name'] == 'Historical bucket'
        assert store.history(7, integration)['current']['unprotected'] == 2
        for point in store.history(7, integration)['series']:
            if point['discovered'] is not None:
                at = datetime.fromisoformat(point['at'])
                replay = store.snapshot(at, integration)
                assert replay['counts'] == {key: point[key] for key in replay['counts']}
        epoch = datetime.fromisoformat(snapshot['recording_started_at'])
        with pytest.raises(ValueError, match='not recorded'):
            store.snapshot(epoch - timedelta(seconds=1), integration)
        conn.execute('DELETE FROM cp_integrations WHERE integration_id = %s', (integration,))
