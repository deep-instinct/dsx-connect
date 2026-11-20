"""Bounded background discovery. Only complete walks may remove known assets."""
import hashlib
import logging

from dsx_connect_v2.control_plane.discovery_settings import DiscoverySettings, discovery_due

from dsx_connect_v2.control_plane.coverage import ProtectionCoverageStore

log = logging.getLogger(__name__)

def asset_identity(integration_id, selector):
    return hashlib.md5((integration_id + '\x1f' + selector.strip().strip('/')).encode()).hexdigest()


def store_page(conn, integration_id, asset_type, assets):
    rows = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get('selector') or raw.get('id') or '').strip()
        if not selector:
            continue
        rows.append((asset_identity(integration_id, selector), integration_id, selector, selector.strip('/'),
                     str(raw.get('display_name') or raw.get('displayName') or selector), asset_type))
    if rows:
        with conn.cursor() as cur:
            cur.executemany('''INSERT INTO cp_discovered_assets
                (asset_id, integration_id, selector, normalized_selector, display_name, asset_type, source)
                VALUES (%s, %s, %s, %s, %s, %s, 'discovery')
                ON CONFLICT (asset_id) DO UPDATE SET selector = EXCLUDED.selector,
                    normalized_selector = EXCLUDED.normalized_selector, display_name = EXCLUDED.display_name,
                    asset_type = EXCLUDED.asset_type, source = 'discovery', active = TRUE, last_seen_at = clock_timestamp()''', rows)


def _refresh_one(store, integration, discover, config=None, should_stop=None):
    config = config or DiscoverySettings()
    with store._connect() as conn:
        # This session lock survives page commits and is released on connection close.
        if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked',
                            ('coverage-inventory:' + integration.integration_id,)).fetchone()['locked']:
            return
        status = conn.execute('SELECT * FROM cp_asset_inventory_status WHERE integration_id = %s', (integration.integration_id,)).fetchone()
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        request = conn.execute('SELECT * FROM cp_discovery_refresh_queue WHERE integration_id = %s AND completed_at IS NULL', (integration.integration_id,)).fetchone()
        if not discovery_due(status, request, config, now):
            return
        request_id = request['request_id'] if request else None
        restart = bool(request and (not status or status.get('active_request_id') != request_id))
        cursor = status['next_cursor'] if status and not restart else None
        started = status['run_started_at'] if cursor and status else now
        failures = status.get('consecutive_failures', 0) if status and not restart else 0
        def save(state, next_cursor=None, detail=None, complete=False):
            conn.execute('''INSERT INTO cp_asset_inventory_status
                (integration_id, state, last_attempt_at, run_started_at, next_cursor, detail, last_completed_at, consecutive_failures, active_request_id)
                VALUES (%s, %s, clock_timestamp(), %s, %s, %s, CASE WHEN %s THEN clock_timestamp() END, %s, %s)
                ON CONFLICT (integration_id) DO UPDATE SET state = EXCLUDED.state,
                    last_attempt_at = EXCLUDED.last_attempt_at, run_started_at = EXCLUDED.run_started_at,
                    next_cursor = EXCLUDED.next_cursor, detail = EXCLUDED.detail,
                    last_completed_at = COALESCE(EXCLUDED.last_completed_at, cp_asset_inventory_status.last_completed_at),
                    consecutive_failures = EXCLUDED.consecutive_failures, active_request_id = EXCLUDED.active_request_id''',
                (integration.integration_id, state, started, next_cursor, detail, complete,
                 0 if complete else failures + 1 if state == 'error' else failures, request_id))
            if request_id and state in {'complete', 'unsupported', 'disabled'}:
                conn.execute('UPDATE cp_discovery_refresh_queue SET completed_at = clock_timestamp(), outcome = %s WHERE integration_id = %s AND request_id = %s', (state, integration.integration_id, request_id))
                conn.execute('UPDATE cp_discovery_refresh_audit SET completed_at = clock_timestamp(), outcome = %s WHERE request_id = %s AND completed_at IS NULL', (state, request_id))
            conn.commit()
        if not integration.enabled:
            save('disabled', detail='Connector disabled; retaining previously discovered assets.')
            return
        if not integration.capability_discover:
            save('unsupported', detail='Connector does not advertise asset discovery.')
            return
        save('refreshing', cursor)
        seen_cursors = set()
        for _ in range(config.max_pages_per_pass):
            if should_stop and should_stop():
                save('partial', cursor)
                return
            try:
                payload, asset_type = discover(integration, cursor)
                if payload.get('unsupported'):
                    save('unsupported', cursor, 'Asset discovery is unavailable for this connector.')
                    return
                if not isinstance(payload.get('assets'), list):
                    raise ValueError('invalid discovery response')
                if payload.get('status') not in {None, 'success'}:
                    raise ValueError('discovery was not successful')
                store_page(conn, integration.integration_id, str(payload.get('asset_type') or asset_type), payload['assets'])
                following = payload.get('next_cursor') or payload.get('nextCursor')
                if following and (not isinstance(following, str) or following == cursor or following in seen_cursors):
                    raise ValueError('discovery cursor did not advance')
                if payload.get('source') in {'configured_asset', 'configured'}:
                    save('unsupported', cursor, 'Only configured assets were returned; complete discovery is unavailable.')
                    return
                if not following:
                    conn.execute('''UPDATE cp_discovered_assets SET active = FALSE
                        WHERE integration_id = %s AND asset_type = %s AND source = 'discovery'
                          AND active AND last_seen_at < %s''', (integration.integration_id, str(payload.get('asset_type') or asset_type), started))
                    save('complete', complete=True)
                    return
                seen_cursors.add(following)
                cursor = following
                save('partial', cursor)
            except Exception as exc:
                log.warning("Discovery attempt failed for %s (%s)", integration.integration_id, type(exc).__name__)
                conn.rollback()
                save('error', cursor, 'Discovery failed; retaining the last known inventory. Retrying automatically.')
                return
