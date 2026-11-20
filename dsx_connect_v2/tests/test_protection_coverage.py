from datetime import datetime, timedelta, timezone

from dsx_connect_v2.control_plane.coverage import coverage_history

NOW = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
START = NOW - timedelta(hours=2)


def event(i, kind, key, state, *, at=START, operation='baseline'):
    return dict(event_id=i, entity_type=kind, entity_id=key, state=state, occurred_at=at, operation=operation)


def baseline():
    return [event(1, 'integration', 'i', dict(enabled=True, capability_monitor=True)),
            event(2, 'scope', 's', dict(integration_id='i', display_name='Bucket A', resource_selector='bucket', enabled=True, mode='full_scan')),
            event(3, 'asset', 'a', dict(integration_id='i', display_name='Bucket A', selector='bucket', normalized_selector='bucket', source='discovery', active=True))]


def test_schedule_granted_and_removed_are_exact_steps_not_daily_averages():
    rows = baseline() + [event(3, 'schedule', 's', dict(enabled=True), at=START + timedelta(minutes=10), operation='INSERT'),
                         event(4, 'schedule', 's', dict(enabled=False), at=START + timedelta(minutes=20), operation='UPDATE')]
    data = coverage_history(rows, START, 7, NOW)
    assert data['current']['unprotected'] == 0
    assert data['current']['scheduled'] == 0
    assert data['series'][0]['unprotected'] is None
    assert data['series'][1]['protected'] == 1
    assert data['series'][2]['scheduled'] == 1
    assert data['series'][3]['protected'] == 1
    assert [change['notes'] for change in data['changes']] == [
        ['Bucket A: Scheduled scan granted'], ['Bucket A: Scheduled scan removed']]
    assert data['series'][2]['at'] == (START + timedelta(minutes=10)).isoformat()


def test_monitoring_and_schedule_can_overlap_and_connector_disable_removes_both():
    rows = baseline()
    rows[1]['state']['mode'] = 'monitor'
    rows += [event(3, 'schedule', 's', dict(enabled=True)),
             event(4, 'integration', 'i', dict(enabled=False, capability_monitor=True),
                   at=START + timedelta(minutes=10), operation='UPDATE')]
    data = coverage_history(rows, START, 1, NOW)
    assert data['series'][1]['scheduled'] == data['series'][1]['monitoring'] == 1
    assert data['current']['unprotected'] == 1
    assert data['changes'][0]['notes'] == ['Bucket A: Protection removed', 'Bucket A: Scheduled scan removed', 'Bucket A: Monitoring removed']


def test_seed_before_window_is_not_reported_as_a_change_and_deleted_scope_is_preserved_in_history():
    rows = baseline()
    for row in rows:
        row['occurred_at'] = NOW - timedelta(days=10)
    rows += [event(3, 'scope', 's', rows[1]['state'], at=START, operation='DELETE')]
    data = coverage_history(rows, NOW - timedelta(days=20), 7, NOW)
    assert data['series'][0]['protected'] == 1
    assert data['series'][0]['at'].startswith('2026-11-13T00:00:00')
    assert data['current']['total'] == 1
    assert data['current']['unprotected'] == 1
    assert data['changes'][0]['notes'] == ['Bucket A: Protection removed']


def test_assigned_scope_is_protected_even_without_monitoring_or_schedule():
    rows = baseline()
    rows[0]['state']['capability_monitor'] = False
    rows[1]['state']['mode'] = 'monitor'
    data = coverage_history(rows, START, 1, NOW)
    assert data['current']['unprotected'] == 0
    assert data['current']['protected'] == 1
    assert data['current']['monitoring'] == 0


def test_future_events_are_excluded_and_empty_inventory_is_valid():
    rows = baseline() + [event(3, 'schedule', 's', dict(enabled=True), at=NOW + timedelta(hours=1), operation='INSERT')]
    assert coverage_history(rows, START, 7, NOW)['current']['scheduled'] == 0
    empty = coverage_history([], START, 7, NOW)
    assert empty['current']['total'] == 0
    assert empty['changes'] == []


def test_discovered_includes_assets_without_scopes_and_subsets_can_overlap():
    rows = baseline()
    rows += [event(10, 'asset', 'b', dict(integration_id='i', display_name='Unassigned', normalized_selector='other', source='discovery', active=True))]
    data = coverage_history(rows, START, 7, NOW)
    assert data['current']['discovered'] == 2
    assert data['current']['protected'] == data['current']['unprotected'] == 1
    for point in data['series']:
        if point['discovered'] is not None:
            assert point['known'] == point['protected'] + point['unprotected']
            assert point['scheduled'] <= point['protected']
            assert point['monitoring'] <= point['protected']


def test_first_discovery_is_not_misreported_as_a_new_protection_grant():
    rows = baseline()
    rows[2]['operation'] = 'INSERT'
    rows[2]['occurred_at'] = START + timedelta(minutes=20)
    data = coverage_history(rows, START, 7, NOW)
    assert data['changes'][0]['notes'] == ['Bucket A: discovered (Protected)']


def test_configured_only_assets_do_not_inflate_discovered_count():
    rows = baseline()
    rows[2]['state']['source'] = 'configuration'
    assert coverage_history(rows, START, 7, NOW)['current']['discovered'] == 0


def test_large_discovery_batch_has_bounded_chart_points_and_preserves_the_accounting_identity():
    rows = baseline()
    rows += [event(20 + i, 'asset', f'asset-{i}', dict(integration_id='i', display_name=f'Asset {i}',
                   normalized_selector=f'other-{i}', source='discovery', active=True),
                   at=START + timedelta(seconds=10, milliseconds=i), operation='INSERT') for i in range(10005)]
    data = coverage_history(rows, START, 7, NOW)
    assert data['current']['discovered'] == 10006
    assert data['current']['protected'] == 1
    assert data['current']['unprotected'] == 10005
    assert len(data['series']) < 10
    assert len(data['changes']) < 10


def test_parent_path_scope_covers_discovered_descendants_with_a_path_boundary():
    rows = baseline()
    rows[1]['state'].update(resource_selector='/bucket', scope_type='path')
    rows += [event(10, 'asset', 'child', dict(integration_id='i', display_name='Child',
                 normalized_selector='bucket/child', source='discovery', active=True)),
             event(11, 'asset', 'other', dict(integration_id='i', display_name='Other',
                 normalized_selector='bucket-other', source='discovery', active=True))]
    current = coverage_history(rows, START, 7, NOW)['current']
    assert current['discovered'] == 3
    assert current['protected'] == 2
    assert current['unprotected'] == 1


def test_snapshot_replays_historical_protection_and_membership_not_current_state():
    from dsx_connect_v2.control_plane.coverage import coverage_snapshot

    rows = baseline()
    disabled = dict(rows[1]['state'], enabled=False)
    rows += [event(30, 'scope', 's', disabled, at=START + timedelta(minutes=30), operation='UPDATE'),
             event(31, 'asset', 'later', dict(integration_id='i', display_name='Later asset', selector='later',
                   normalized_selector='later', source='discovery', active=True),
                   at=START + timedelta(minutes=40), operation='INSERT')]
    before = coverage_snapshot(rows, START + timedelta(minutes=20))
    assert before['total'] == before['counts']['protected'] == 1
    assert before['assets'][0]['protected'] is True
    after = coverage_snapshot(rows, NOW, offset=1, limit=1)
    assert after['total'] == after['counts']['unprotected'] == 2
    assert len(after['assets']) == 1
    assert after['counts']['protected'] == 0


def test_configured_assets_are_known_and_protected_before_discovery_without_double_counting():
    from dsx_connect_v2.control_plane.coverage import coverage_snapshot
    rows = baseline()
    rows[2]['state']['source'] = 'configuration'
    first = coverage_history(rows, START, 7, NOW)['current']
    assert first['known'] == first['total'] == first['protected'] == 1
    assert first['discovered'] == first['unprotected'] == 0
    promoted = dict(rows[2]['state'], source='discovery')
    rows.append(event(10, 'asset', 'a', promoted, at=START + timedelta(minutes=10), operation='UPDATE'))
    data = coverage_history(rows, START, 7, NOW)
    assert data['current']['known'] == data['current']['discovered'] == data['current']['protected'] == 1
    assert data['changes'][0]['notes'] == ['Bucket A: discovery confirmed']
    snapshot = coverage_snapshot(rows, START + timedelta(minutes=5))
    assert snapshot['counts']['known'] == 1 and snapshot['counts']['discovered'] == 0
    assert snapshot['assets'][0]['discovered'] is False


def test_configured_asset_removed_with_last_scope_but_disabled_scope_remains_known():
    rows = baseline()
    rows[2]['state']['source'] = 'configuration'
    rows.append(event(10, 'scope', 's', dict(rows[1]['state'], enabled=False), at=START + timedelta(minutes=10), operation='UPDATE'))
    current = coverage_history(rows, START, 7, NOW)['current']
    assert current['known'] == current['unprotected'] == 1 and current['protected'] == 0
    rows.append(event(11, 'scope', 's', rows[1]['state'], at=START + timedelta(minutes=20), operation='DELETE'))
    current = coverage_history(rows, START, 7, NOW)['current']
    assert current['known'] == current['discovered'] == current['protected'] == 0


def test_asset_missing_from_completed_discovery_remains_known_through_configuration():
    rows = baseline()
    rows.append(event(10, 'asset', 'a', dict(rows[2]['state'], active=False), at=START + timedelta(minutes=10), operation='UPDATE'))
    current = coverage_history(rows, START, 7, NOW)['current']
    assert current['known'] == current['protected'] == 1 and current['discovered'] == 0
    assert current['known'] == current['protected'] + current['unprotected']
