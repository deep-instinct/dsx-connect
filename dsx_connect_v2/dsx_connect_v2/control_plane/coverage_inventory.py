"""Bounded background discovery. Only complete walks may remove known assets."""
import hashlib
import threading

from dsx_connect_v2.control_plane.coverage import ProtectionCoverageStore

_running = set()
_guard = threading.Lock()


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


def start_inventory_refresh(db_url, control_plane, discover, integration_id=None):
    """One bounded sweep per API process; database locks prevent cross-process duplicates."""
    with _guard:
        if db_url in _running:
            return
        _running.add(db_url)
    def run():
        try:
            store = ProtectionCoverageStore(db_url)
            for integration in control_plane.list_integrations():
                if integration_id and integration.integration_id != integration_id:
                    continue
                _refresh_one(store, integration, discover)
        finally:
            with _guard:
                _running.discard(db_url)
    threading.Thread(target=run, name='coverage-inventory', daemon=True).start()


def _refresh_one(store, integration, discover):
    with store._connect() as conn:
        # This session lock survives page commits and is released on connection close.
        if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked',
                            ('coverage-inventory:' + integration.integration_id,)).fetchone()['locked']:
            return
        status = conn.execute('SELECT * FROM cp_asset_inventory_status WHERE integration_id = %s', (integration.integration_id,)).fetchone()
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        delay = 5 if status and status['state'] in {'partial', 'refreshing'} else 60 if status and status['state'] == 'error' else 300
        if status and (now - status['last_attempt_at']).total_seconds() < delay and not (status['state'] == 'disabled' and integration.enabled):
            return
        cursor = status['next_cursor'] if status else None
        started = status['run_started_at'] if cursor and status else now
        def save(state, next_cursor=None, detail=None, complete=False):
            conn.execute('''INSERT INTO cp_asset_inventory_status
                (integration_id, state, last_attempt_at, run_started_at, next_cursor, detail, last_completed_at)
                VALUES (%s, %s, clock_timestamp(), %s, %s, %s, CASE WHEN %s THEN clock_timestamp() END)
                ON CONFLICT (integration_id) DO UPDATE SET state = EXCLUDED.state,
                    last_attempt_at = EXCLUDED.last_attempt_at, run_started_at = EXCLUDED.run_started_at,
                    next_cursor = EXCLUDED.next_cursor, detail = EXCLUDED.detail,
                    last_completed_at = COALESCE(EXCLUDED.last_completed_at, cp_asset_inventory_status.last_completed_at)''',
                (integration.integration_id, state, started, next_cursor, detail, complete))
            conn.commit()
        if not integration.enabled:
            save('disabled', detail='Connector disabled; retaining previously discovered assets.')
            return
        if not integration.capability_discover:
            save('unsupported', detail='Connector does not advertise asset discovery.')
            return
        save('refreshing', cursor)
        seen_cursors = set()
        for _ in range(10):
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
            except Exception:
                conn.rollback()
                save('error', cursor, 'Discovery failed; retaining the last known inventory. Retrying automatically.')
                return
