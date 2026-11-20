"""Persisted discovery policy, manual work requests, and worker health."""
from datetime import timedelta

from pydantic import BaseModel, Field, model_validator

from dsx_connect_v2.control_plane.coverage import ProtectionCoverageStore


class DiscoverySettings(BaseModel):
    periodic_enabled: bool = True
    interval_seconds: int = Field(default=300, ge=30, le=86400)
    concurrency: int = Field(default=2, ge=1, le=16)
    retry_initial_seconds: int = Field(default=60, ge=5, le=3600)
    retry_max_seconds: int = Field(default=900, ge=5, le=86400)
    max_pages_per_pass: int = Field(default=10, ge=1, le=100)
    request_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @model_validator(mode='after')
    def validate_backoff(self):
        if self.retry_max_seconds < self.retry_initial_seconds:
            raise ValueError('Maximum retry delay must be at least the initial retry delay.')
        return self


def discovery_due(status, request, config, now):
    pending = request and request.get('completed_at') is None
    new_request = bool(pending and (not status or status.get('active_request_id') != request['request_id']))
    if new_request:
        return True
    if not config.periodic_enabled and not pending:
        return False
    if not status:
        return True
    if status['state'] in {'partial', 'refreshing'}:
        delay = 5
    elif status['state'] == 'error':
        failures = max(0, status.get('consecutive_failures', 0) - 1)
        delay = min(config.retry_max_seconds, config.retry_initial_seconds * 2 ** min(failures, 16))
    else:
        delay = config.interval_seconds
    return now >= status['last_attempt_at'] + timedelta(seconds=delay)


class DiscoverySettingsStore(ProtectionCoverageStore):
    def settings(self):
        with self._connect() as conn:
            row = conn.execute('SELECT settings, revision, updated_at FROM cp_discovery_settings WHERE singleton').fetchone()
        return {**row, 'settings': DiscoverySettings.model_validate(row['settings']).model_dump()}

    def save_settings(self, settings, expected_revision):
        with self._connect() as conn:
            current = conn.execute('SELECT * FROM cp_discovery_settings WHERE singleton FOR UPDATE').fetchone()
            if current['revision'] != expected_revision:
                raise ValueError('Settings changed since this page was loaded. Reload settings before saving.')
            values = settings.model_dump()
            if values != current['settings']:
                from psycopg.types.json import Jsonb
                conn.execute('INSERT INTO cp_discovery_settings_audit(revision, previous_settings, settings) VALUES (%s,%s,%s)',
                             (current['revision'] + 1, Jsonb(current['settings']), Jsonb(values)))
                conn.execute('UPDATE cp_discovery_settings SET settings = %s, revision = revision + 1, updated_at = clock_timestamp() WHERE singleton', (Jsonb(values),))
        return self.settings()

    def request(self, integration_ids, reason='manual'):
        with self._connect() as conn:
            result = [dict(integration_id=key, request_id=conn.execute('SELECT cp_queue_discovery_refresh(%s,%s) AS token', (key, reason)).fetchone()['token']) for key in integration_ids]
        return result

    def status(self):
        with self._connect() as conn:
            inventory = conn.execute('''SELECT i.integration_id, i.display_name, i.enabled, i.capability_discover,
                COALESCE(s.state, 'pending') AS state, s.last_attempt_at, s.last_completed_at,
                COALESCE(s.consecutive_failures, 0) AS consecutive_failures, s.detail,
                q.request_id, q.reason, q.requested_at, q.completed_at AS request_completed_at, q.outcome AS request_outcome
                FROM cp_integrations i LEFT JOIN cp_asset_inventory_status s USING(integration_id)
                LEFT JOIN cp_discovery_refresh_queue q USING(integration_id) ORDER BY i.display_name''').fetchall()
            workers = conn.execute('''SELECT worker_id, started_at, last_heartbeat_at, active_connectors,
                last_heartbeat_at >= clock_timestamp() - INTERVAL '30 seconds' AS healthy
                FROM cp_discovery_workers ORDER BY last_heartbeat_at DESC LIMIT 20''').fetchall()
        return {'inventory': inventory, 'workers': workers, 'healthy_workers': sum(row['healthy'] for row in workers)}

    def heartbeat(self, worker_id, active):
        with self._connect() as conn:
            conn.execute('''INSERT INTO cp_discovery_workers(worker_id, active_connectors) VALUES (%s,%s)
                ON CONFLICT(worker_id) DO UPDATE SET last_heartbeat_at = clock_timestamp(), active_connectors = EXCLUDED.active_connectors''', (worker_id, active))
            conn.execute("DELETE FROM cp_discovery_workers WHERE last_heartbeat_at < clock_timestamp() - INTERVAL '7 days'")

    def due_integrations(self, integrations, config):
        with self._connect() as conn:
            now = conn.execute('SELECT clock_timestamp() AS now').fetchone()['now']
            statuses = {row['integration_id']: row for row in conn.execute('SELECT * FROM cp_asset_inventory_status').fetchall()}
            requests = {row['integration_id']: row for row in conn.execute('SELECT * FROM cp_discovery_refresh_queue WHERE completed_at IS NULL').fetchall()}
        due = [row for row in integrations if discovery_due(statuses.get(row.integration_id), requests.get(row.integration_id), config, now)]
        due.sort(key=lambda row: (row.integration_id not in requests,
                                 requests[row.integration_id]['requested_at'] if row.integration_id in requests else statuses.get(row.integration_id, {}).get('last_attempt_at') or now))
        return due
