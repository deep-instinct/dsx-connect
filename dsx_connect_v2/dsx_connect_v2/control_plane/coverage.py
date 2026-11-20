"""Replay configuration audit events without loading scan or file records."""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from itertools import groupby


def coverage_window(days, now):
    floor = now.replace(minute=0, second=0, microsecond=0)
    if days != 1:
        floor = floor.replace(hour=0)
    return floor - (timedelta(hours=23) if days == 1 else timedelta(days=days - 1))


def _capabilities(state, asset_ids, scopes):
    result = {}
    for asset_id in asset_ids:
        asset = state.get(('asset', asset_id), {})
        if not asset:
            continue
        integration = state.get(('integration', asset['integration_id']), {})
        selector = asset['normalized_selector']
        matches = list(scopes.get((asset['integration_id'], selector), []))
        discovered = asset.get('active', True) and asset.get('source') == 'discovery'
        # Configured selectors remain known even when enumeration fails or stops returning them.
        # Historical configuration-only rows without a remaining scope are not inventory.
        if not discovered and not matches:
            continue
        ancestor = selector
        while '/' in ancestor:
            ancestor = ancestor.rsplit('/', 1)[0]
            matches += [(key, scope) for key, scope in scopes.get((asset['integration_id'], ancestor), []) if scope.get('scope_type') == 'path']
        if selector:
            matches += [(key, scope) for key, scope in scopes.get((asset['integration_id'], ''), []) if scope.get('scope_type') == 'path']
        enabled = [(scope_id, scope) for scope_id, scope in matches if scope.get('enabled') and integration.get('enabled')]
        protected = bool(enabled)
        monitoring = any(scope.get('mode') == 'monitor' and integration.get('capability_monitor', False) for _, scope in enabled)
        scheduled = any(state.get(('schedule', scope_id), {}).get('enabled', False) for scope_id, _ in enabled)
        result[asset_id] = {'name': asset['display_name'], 'monitoring': bool(monitoring), 'scheduled': bool(scheduled),
                            'protected': protected, 'unprotected': not protected, 'known': True, 'discovered': bool(discovered)}
    return result


def coverage_history(events, started_at, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    start = coverage_window(days, now)
    state, scope_states, scope_index = {}, {}, {}
    assets_by_integration = defaultdict(set)
    totals = dict.fromkeys(('known', 'discovered', 'unprotected', 'protected', 'scheduled', 'monitoring'), 0)
    series, changes = [], deque(maxlen=100)
    change_count = 0
    resolution = {1: 60, 7: 300, 30: 900}[days]
    last_discovery_bin = None

    def point(at, notes=None):
        return {'at': at.isoformat(), 'total': totals['known'], **totals, 'notes': notes or []}

    ordered = sorted((event for event in events if event['occurred_at'] <= now),
                     key=lambda event: (event['occurred_at'], event['event_id']))
    for at, group in groupby(ordered, key=lambda event: event['occurred_at']):
        group = list(group)
        if at > start and not series:
            series.append(point(start) if started_at <= start else {
                'at': start.isoformat(), **dict.fromkeys(totals), 'notes': ['History was not recorded yet.']})
        affected = set()
        for event in group:
            kind, key = event['entity_type'], event['entity_id']
            if kind == 'asset':
                affected.add(key)
            else:
                row = event['state'] if kind != 'schedule' else state.get(('scope', key), {})
                integration = key if kind == 'integration' else row.get('integration_id')
                affected.update(assets_by_integration.get(integration, ()))
        before = _capabilities(state, affected, scope_index)
        scopes_changed = False
        for event in group:
            kind, entity = event['entity_type'], event['entity_id']
            key = (kind, entity)
            if event['operation'] == 'DELETE':
                state.pop(key, None)
                if kind == 'scope':
                    scope_states.pop(entity, None)
                    scopes_changed = True
            else:
                state[key] = event['state']
                if kind == 'scope':
                    scope_states[entity] = event['state']
                    scopes_changed = True
                elif kind == 'asset':
                    assets_by_integration[event['state']['integration_id']].add(entity)
        if scopes_changed:
            scope_index = {}
            for key, scope in scope_states.items():
                selector = scope.get('resource_selector', '').strip().strip('/')
                scope_index.setdefault((scope['integration_id'], selector), []).append((key, scope))
        after = _capabilities(state, affected, scope_index)
        for values, sign in [(before.values(), -1), (after.values(), 1)]:
            for row in values:
                for key in totals:
                    totals[key] += sign * row[key]
        if at < start:
            continue
        notes = []
        note_count = 0
        def add_note(note):
            nonlocal note_count
            note_count += 1
            if len(notes) < 5:
                notes.append(note)
        baseline = all(event['operation'] == 'baseline' for event in group)
        inventory_only = all(event['entity_type'] == 'asset' for event in group) and not baseline
        if not baseline:
            for asset_id in sorted(before.keys() | after.keys()):
                old, new = before.get(asset_id), after.get(asset_id)
                name = (new or old)['name']
                if old is None:
                    add_note(f'{name}: {"discovered" if new["discovered"] else "configured"} ({"Protected" if new["protected"] else "Unprotected"})')
                    continue
                if new is None:
                    add_note(f'{name}: removed from {"discovered" if old["discovered"] else "known"} inventory')
                    continue
                if old['discovered'] != new['discovered']:
                    add_note(f'{name}: {"discovery confirmed" if new["discovered"] else "retained from configuration; no longer returned by discovery"}')
                for capability, label in [('protected', 'Protection'), ('scheduled', 'Scheduled scan'), ('monitoring', 'Monitoring')]:
                    if old[capability] != new[capability]:
                        add_note(f'{name}: {label} {"granted" if new[capability] else "removed"}')
            if not notes:
                for event in group:
                    if event['operation'] != 'baseline':
                        add_note(f"{event['entity_type'].title()} configuration {event['operation'].lower()}: "
                                 f"{event['state'].get('display_name', event['entity_id'])}")
            if note_count > len(notes):
                notes.append(f'Plus {note_count - len(notes)} other changes.')
            change_count += 1
        else:
            notes = ['Recording started: current configuration baseline.']
        discovery_bin = int(at.timestamp()) // resolution if inventory_only else None
        if inventory_only and discovery_bin == last_discovery_bin:
            notes = notes[:5] + ['Discovery updates consolidated within this interval.']
            series[-1] = point(at, notes)
            changes[-1] = {'at': at.isoformat(), 'notes': notes}
        else:
            series.append(point(at, notes))
            if not baseline:
                changes.append({'at': at.isoformat(), 'notes': notes})
        last_discovery_bin = discovery_bin
    if not series:
        series.append(point(max(start, started_at)))
    current = point(now)
    if series[-1]['at'] != now.isoformat():
        series.append(current)
    return {'start': start.isoformat(), 'end': now.isoformat(), 'recording_started_at': started_at.isoformat(),
            'bucket': 'hour' if days == 1 else 'day', 'time_scale': True, 'step': True,
            'discovery_resolution_seconds': resolution,
            'series': series, 'current': current, 'changes': list(changes), 'changes_count': change_count}


class ProtectionCoverageStore:
    def __init__(self, db_url):
        self.db_url = db_url

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.db_url, row_factory=dict_row)

    def asset_counts(self, integration_ids):
        """Current connector inventory counts without audit replay or cloud enumeration."""
        if not integration_ids:
            return {'discovered': 0, 'protected': 0}
        with self._connect() as conn:
            row = conn.execute("""SELECT
                count(*) FILTER (WHERE a.active AND a.source = 'discovery') AS discovered,
                count(*) FILTER (WHERE i.enabled AND EXISTS (
                    SELECT 1 FROM cp_scopes s WHERE s.integration_id = a.integration_id AND s.enabled
                    AND (btrim(btrim(s.resource_selector), '/') = a.normalized_selector
                    OR (s.scope_type = 'path' AND (btrim(btrim(s.resource_selector), '/') = ''
                        OR starts_with(a.normalized_selector, btrim(btrim(s.resource_selector), '/') || '/')))))) AS protected
                FROM cp_discovered_assets a JOIN cp_integrations i USING(integration_id)
                WHERE a.integration_id = ANY(%s::text[])
                AND ((a.active AND a.source = 'discovery') OR EXISTS (
                    SELECT 1 FROM cp_scopes configured WHERE configured.integration_id = a.integration_id
                    AND btrim(btrim(configured.resource_selector), '/') = a.normalized_selector))
                """, (list(integration_ids),)).fetchone()
        return dict(row)

    def protected_count(self, integration_ids):
        return self.asset_counts(integration_ids)['protected']

    def revision(self, integration_id=None):
        with self._connect() as conn:
            row = conn.execute('SELECT revision FROM cp_protection_revision WHERE integration_id = %s',
                               (integration_id or '*',)).fetchone()
        return row['revision'] if row else 0

    def snapshot(self, at, integration_id=None, *, offset=0, limit=100):
        with self._connect() as conn:
            epoch = conn.execute('SELECT started_at FROM cp_protection_audit_epoch WHERE singleton').fetchone()['started_at']
            if at < epoch:
                raise ValueError('Protection history was not recorded at this time.')
            rows = conn.execute("""SELECT DISTINCT ON (entity_type, entity_id) *
                FROM cp_protection_events WHERE occurred_at <= %s
                AND (%s::text IS NULL OR integration_id = %s)
                ORDER BY entity_type, entity_id, occurred_at DESC, event_id DESC""",
                (at, integration_id, integration_id)).fetchall()
        result = coverage_snapshot(rows, at, offset=offset, limit=limit)
        result['recording_started_at'] = epoch.isoformat()
        return result

    def history(self, days, integration_id=None, now=None):
        now = now or datetime.now(timezone.utc)
        start = coverage_window(days, now)
        with self._connect() as conn:
            epoch = conn.execute('SELECT started_at FROM cp_protection_audit_epoch WHERE singleton').fetchone()['started_at']
            events = conn.execute('''
                (SELECT DISTINCT ON (entity_type, entity_id) * FROM cp_protection_events
                 WHERE occurred_at < %s AND (%s::text IS NULL OR integration_id = %s)
                 ORDER BY entity_type, entity_id, occurred_at DESC, event_id DESC)
                UNION ALL
                (SELECT * FROM cp_protection_events WHERE occurred_at BETWEEN %s AND %s
                 AND (%s::text IS NULL OR integration_id = %s))
                ''', (start, integration_id, integration_id, start, now, integration_id, integration_id)).fetchall()
            inventory = conn.execute("""SELECT i.integration_id, i.display_name,
                       COALESCE(s.state, 'pending') AS state, s.last_attempt_at, s.last_completed_at, s.detail
                FROM cp_integrations i LEFT JOIN cp_asset_inventory_status s USING(integration_id)
                WHERE (%s::text IS NULL OR i.integration_id = %s) ORDER BY i.display_name""",
                (integration_id, integration_id)).fetchall()
        data = coverage_history(events, epoch, days, now)
        data['inventory'] = inventory
        return data


def coverage_snapshot(events, at, *, offset=0, limit=100):
    """Return the recorded asset membership and capabilities at an exact instant."""
    state = {}
    for event in sorted(events, key=lambda row: (row['occurred_at'], row['event_id'])):
        if event['occurred_at'] > at:
            continue
        key = (event['entity_type'], event['entity_id'])
        if event['operation'] == 'DELETE':
            state.pop(key, None)
        else:
            state[key] = event['state']
    scopes = {}
    for (kind, key), scope in state.items():
        if kind == 'scope':
            scopes.setdefault((scope['integration_id'], scope.get('resource_selector', '').strip().strip('/')), []).append((key, scope))
    assets = _capabilities(state, {key for kind, key in state if kind == 'asset'}, scopes)
    rows = []
    for key, capabilities in assets.items():
        asset = state[('asset', key)]
        integration = state.get(('integration', asset['integration_id']), {})
        rows.append({'asset_id': key, **capabilities, 'selector': asset['selector'],
                     'integration_id': asset['integration_id'],
                     'connector': integration.get('display_name', asset['integration_id'])})
    rows.sort(key=lambda row: (row['connector'].casefold(), row['name'].casefold(), row['asset_id']))
    counts = {key: sum(row[key] for row in rows) for key in ('known', 'discovered', 'unprotected', 'protected', 'scheduled', 'monitoring')}
    return {'at': at.isoformat(), 'counts': counts, 'total': len(rows), 'offset': offset, 'limit': limit,
            'assets': rows[offset:offset + limit]}
