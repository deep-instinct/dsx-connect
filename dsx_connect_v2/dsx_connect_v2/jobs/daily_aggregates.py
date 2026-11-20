"""Durable UTC-day summaries, independently retained from detailed results."""
from datetime import datetime, timedelta, timezone
import logging

from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from dsx_connect_v2.control_plane.coverage import ProtectionCoverageStore

log = logging.getLogger(__name__)


class ManagementSettings(BaseModel):
    aggregates_enabled: bool = True
    aggregate_interval_seconds: int = Field(default=300, ge=30, le=86400)
    aggregate_days_per_pass: int = Field(default=1, ge=1, le=10)


# Bounds are half-open UTC days. All reductions happen in PostgreSQL, not Python file lists.
ITEMS_SQL = '''WITH stages AS MATERIALIZED (
    SELECT scan.*, item.report_scan_completed_at AS completed_at, item.policy_stage_json AS policy, item.remediation_stage_json AS remediation
    FROM cp_job_items item JOIN cp_jobs job USING(job_id)
    CROSS JOIN LATERAL jsonb_to_record(item.scan_stage_json)
      AS scan(state text, result jsonb, metadata jsonb)
    WHERE job.job_type <> 'protection.bulk' AND COALESCE(job.integration_id,'') = %(integration)s
      AND (item.report_scan_completed_at >= %(start)s AND item.report_scan_completed_at < %(end)s
        OR item.report_policy_completed_at >= %(start)s AND item.report_policy_completed_at < %(end)s
        OR item.report_remediation_completed_at >= %(start)s AND item.report_remediation_completed_at < %(end)s)
), facts AS MATERIALIZED (
    SELECT *, state = 'completed' AND completed_at >= %(start)s AND completed_at < %(end)s AS scanned,
      lower(COALESCE(result->>'verdict','')) AS verdict,
      COALESCE(result->'file_info'->>'file_type',result->'file_info'->>'fileType',result->'fileInfo'->>'file_type',
        result->'fileInfo'->>'fileType',result->>'fileType',result->>'file_type','Unknown') AS file_type,
      COALESCE(policy->'result'->'policy_stage_result',policy->'result') AS decision
    FROM stages
), decisions AS MATERIALIZED (
    SELECT *, starts_with(COALESCE(decision->'decision_trace'->>'policy_reason',decision->'decisionTrace'->>'policy_reason',''),'blocked_file_type:') AS type_block,
      remediation->>'state' = 'completed' AND cp_aggregate_day(remediation->>'completed_at') = %(day)s
        AND remediation->'result'->>'action' = 'quarantine' AND remediation->'result'->>'outcome' = 'succeeded' AS quarantined
    FROM facts
)
SELECT jsonb_build_object(
    'total',count(*) FILTER(WHERE scanned),
    'benign',count(*) FILTER(WHERE scanned AND verdict IN ('benign','clean')),
    'malicious',count(*) FILTER(WHERE scanned AND verdict = 'malicious'),
    'suspicious',count(*) FILTER(WHERE scanned AND verdict = 'suspicious'),
    'other',count(*) FILTER(WHERE scanned AND verdict NOT IN ('benign','clean','malicious','suspicious')),
    'file_type_policy_matches',count(*) FILTER(WHERE policy->>'state' = 'completed' AND cp_aggregate_day(policy->>'completed_at') = %(day)s AND type_block),
    'quarantined',jsonb_build_object(
      'malicious',count(*) FILTER(WHERE quarantined AND NOT type_block AND verdict = 'malicious'),
      'suspicious',count(*) FILTER(WHERE quarantined AND NOT type_block AND verdict = 'suspicious'),
      'file_type_policy',count(*) FILTER(WHERE quarantined AND type_block),
      'other',count(*) FILTER(WHERE quarantined AND NOT type_block AND verdict NOT IN ('malicious','suspicious'))),
    'file_types',COALESCE((SELECT jsonb_object_agg(file_type,n) FROM (SELECT file_type,count(*) n FROM decisions WHERE scanned GROUP BY file_type) t),'{}'::jsonb)
) AS summary FROM decisions'''

TIMINGS_SQL = '''WITH raw AS (
    SELECT item.report_scan_completed_at AS completed_at, scan.result, scan.metadata
    FROM cp_job_items item JOIN cp_jobs job USING(job_id)
    CROSS JOIN LATERAL jsonb_to_record(item.scan_stage_json)
      AS scan(state text, result jsonb, metadata jsonb)
    WHERE job.job_type <> 'protection.bulk' AND COALESCE(job.integration_id,'') = %(integration)s
      AND scan.state='completed' AND item.report_scan_completed_at >= %(start)s AND item.report_scan_completed_at < %(end)s
), samples AS (
    SELECT 'scan_worker' metric, COALESCE(
      CASE WHEN jsonb_typeof(metadata->'workerElapsedMs')='number' AND (metadata->>'workerElapsedMs')::double precision >= 0 THEN (metadata->>'workerElapsedMs')::double precision/1000 END,
      CASE WHEN jsonb_typeof(metadata->'requestElapsedMs')='number' AND (metadata->>'requestElapsedMs')::double precision >= 0 THEN (metadata->>'requestElapsedMs')::double precision/1000 END) seconds FROM raw
    UNION ALL SELECT 'dsxa', COALESCE(
      CASE WHEN jsonb_typeof(result->'scan_duration_in_microseconds')='number' AND (result->>'scan_duration_in_microseconds')::double precision >= 0 THEN (result->>'scan_duration_in_microseconds')::double precision/1000000 END,
      CASE WHEN jsonb_typeof(metadata->'scannerEngineElapsedMs')='number' AND (metadata->>'scannerEngineElapsedMs')::double precision >= 0 THEN (metadata->>'scannerEngineElapsedMs')::double precision/1000 END) FROM raw
    UNION ALL SELECT 'job_duration',extract(epoch FROM completed_at-created_at)::double precision FROM cp_jobs
      WHERE job_type <> 'protection.bulk' AND state='completed' AND COALESCE(integration_id,'')=%(integration)s
        AND completed_at >= %(start)s AND completed_at < %(end)s AND completed_at >= created_at
)
SELECT metric,count(seconds) AS samples, sum(seconds) AS sum_seconds, min(seconds) AS min_seconds,
    percentile_cont(0.5) WITHIN GROUP(ORDER BY seconds) AS median_seconds,
    percentile_disc(0.95) WITHIN GROUP(ORDER BY seconds) AS p95_seconds,
    percentile_disc(0.99) WITHIN GROUP(ORDER BY seconds) AS p99_seconds, max(seconds) AS max_seconds
FROM samples WHERE seconds IS NOT NULL GROUP BY metric'''


class DailyAggregateStore(ProtectionCoverageStore):
    def settings(self):
        with self._connect() as conn:
            row = conn.execute('SELECT settings,revision,updated_at FROM cp_management_settings WHERE singleton').fetchone()
        return {**row, 'settings': ManagementSettings(**row['settings']).model_dump()}

    def save_settings(self, policy, expected_revision):
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM cp_management_settings WHERE singleton FOR UPDATE').fetchone()
            if row['revision'] != expected_revision:
                raise ValueError('Management settings changed. Reload before saving.')
            values = policy.model_dump()
            if values != row['settings']:
                conn.execute('INSERT INTO cp_management_settings_audit(revision,previous_settings,settings) VALUES(%s,%s,%s)',
                             (row['revision']+1,Jsonb(row['settings']),Jsonb(values)))
                conn.execute('UPDATE cp_management_settings SET settings=%s, revision=revision+1, updated_at=clock_timestamp() WHERE singleton',(Jsonb(values),))
        return self.settings()

    def heartbeat(self, worker_id):
        with self._connect() as conn:
            conn.execute('INSERT INTO cp_management_workers(worker_id) VALUES(%s) ON CONFLICT(worker_id) DO UPDATE SET last_heartbeat_at=clock_timestamp()', (worker_id,))
            conn.execute("DELETE FROM cp_management_workers WHERE last_heartbeat_at < clock_timestamp()-INTERVAL '7 days'")

    def status(self):
        with self._connect() as conn:
            workers = conn.execute("SELECT worker_id,last_heartbeat_at,last_heartbeat_at >= clock_timestamp()-INTERVAL '30 seconds' AS healthy FROM cp_management_workers ORDER BY last_heartbeat_at DESC LIMIT 20").fetchall()
            task = conn.execute("SELECT * FROM cp_management_tasks WHERE task='daily_aggregates'").fetchone()
            summary = conn.execute('SELECT count(*) AS connector_days,min(day) AS first_day,max(day) AS last_day,max(computed_at) AS latest_computed_at FROM cp_daily_scan_aggregates').fetchone()
            queue = conn.execute('SELECT count(*) AS pending_days FROM cp_daily_aggregate_queue').fetchone()
            gaps = conn.execute('SELECT count(*) AS detail_gaps FROM cp_daily_aggregate_detail_gaps').fetchone()
            backfill = conn.execute('SELECT source,complete FROM cp_management_backfill ORDER BY source').fetchall()
        return dict(workers=workers,healthy_workers=sum(row['healthy'] for row in workers),task=task,summary=summary,**queue,**gaps,backfill=backfill)

    def backfill_page(self, limit=5000):
        """A restartable bounded keyset walk; triggers cover inserts behind the cursor."""
        with self._connect() as conn:
            if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('management:backfill',0)) AS locked").fetchone()['locked']:
                return
            progress = conn.execute('SELECT * FROM cp_management_backfill WHERE NOT complete ORDER BY source LIMIT 1 FOR UPDATE').fetchone()
            if not progress:
                return
            if progress['source'] == 'items':
                rows = conn.execute('''SELECT item.job_item_id AS id,job.integration_id,
                    cp_aggregate_day(item.scan_stage_json->>'completed_at') AS scan_day,
                    cp_aggregate_day(item.policy_stage_json->>'completed_at') AS policy_day,
                    cp_aggregate_day(item.remediation_stage_json->>'completed_at') AS remediation_day
                    FROM cp_job_items item JOIN cp_jobs job USING(job_id)
                    WHERE job.job_type <> 'protection.bulk' AND item.job_item_id > %s ORDER BY item.job_item_id LIMIT %s''', (progress['last_id'],limit)).fetchall()
                if rows:
                    conn.execute("""UPDATE cp_job_items SET
                        report_scan_completed_at=cp_aggregate_timestamp(scan_stage_json->>'completed_at'),
                        report_policy_completed_at=cp_aggregate_timestamp(policy_stage_json->>'completed_at'),
                        report_remediation_completed_at=cp_aggregate_timestamp(remediation_stage_json->>'completed_at')
                        WHERE job_item_id=ANY(%s::text[])""",([row['id'] for row in rows],))
                days = [(row['integration_id'],row[key]) for row in rows for key in ('scan_day','policy_day','remediation_day')]
            else:
                rows = conn.execute("SELECT job_id AS id,integration_id,(completed_at AT TIME ZONE 'UTC')::date AS day FROM cp_jobs WHERE job_id > %s AND job_type <> 'protection.bulk' ORDER BY job_id LIMIT %s",(progress['last_id'],limit)).fetchall()
                days = [(row['integration_id'],row['day']) for row in rows]
            for integration, day in set(days):
                if day:
                    conn.execute('SELECT cp_queue_daily_aggregate(%s,%s)',(day,integration))
            conn.execute('UPDATE cp_management_backfill SET last_id=%s,complete=%s WHERE source=%s',
                         (rows[-1]['id'] if rows else progress['last_id'],len(rows)<limit,progress['source']))

    def backfill_complete(self):
        with self._connect() as conn:
            return not conn.execute('SELECT EXISTS(SELECT 1 FROM cp_management_backfill WHERE NOT complete) AS pending').fetchone()['pending']

    def process_one(self):
        with self._connect() as conn:
            conn.execute("SET LOCAL statement_timeout='60s'")
            if not conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('management:daily-aggregates',0)) AS locked").fetchone()['locked']:
                return False
            row = conn.execute('SELECT * FROM cp_daily_aggregate_queue WHERE available_at<=clock_timestamp() AND NOT EXISTS (SELECT 1 FROM cp_daily_aggregate_detail_gaps g WHERE g.day=cp_daily_aggregate_queue.day AND g.integration_id=cp_daily_aggregate_queue.integration_id) ORDER BY requested_at,day,integration_id LIMIT 1').fetchone()
            if not row:
                return False
            start = datetime.combine(row['day'],datetime.min.time(),timezone.utc)
            params = dict(day=row['day'],start=start,end=start+timedelta(days=1),integration=row['integration_id'])
            with self._connect() as status_conn:
                status_conn.execute("UPDATE cp_management_tasks SET state='running',last_attempt_at=clock_timestamp(),detail=NULL WHERE task='daily_aggregates'")
            summary = conn.execute(ITEMS_SQL,params).fetchone()['summary']
            summary['timings'] = {r['metric']:{key:value for key,value in r.items() if key != 'metric'} for r in conn.execute(TIMINGS_SQL,params).fetchall()}
            summary['jobs'] = {r['state']:r['count'] for r in conn.execute("SELECT state,count(*) FROM cp_jobs WHERE job_type <> 'protection.bulk' AND state IN ('completed','failed','cancelled') AND COALESCE(integration_id,'')=%(integration)s AND completed_at >= %(start)s AND completed_at < %(end)s GROUP BY state",params).fetchall()}
            summary['schema_version'] = 1
            summary['integration_id'] = row['integration_id']
            conn.execute('''INSERT INTO cp_daily_scan_aggregates(day,integration_id,summary) VALUES(%s,%s,%s)
                ON CONFLICT(day,integration_id) DO UPDATE SET summary=EXCLUDED.summary,computed_at=clock_timestamp()
                WHERE NOT EXISTS(SELECT 1 FROM cp_daily_aggregate_detail_gaps g WHERE g.day=EXCLUDED.day AND g.integration_id=EXCLUDED.integration_id)''', (row['day'],row['integration_id'],Jsonb(summary)))
            conn.execute('DELETE FROM cp_daily_aggregate_queue WHERE day=%s AND integration_id=%s AND revision=%s',(row['day'],row['integration_id'],row['revision']))
            conn.execute("UPDATE cp_management_tasks SET state='idle',last_completed_at=clock_timestamp(),detail=NULL WHERE task='daily_aggregates'")
        return True

    def record_error(self):
        with self._connect() as conn:
            conn.execute("UPDATE cp_management_tasks SET state='error',last_attempt_at=clock_timestamp(),detail='Daily aggregation failed; queued work is retained for retry.' WHERE task='daily_aggregates'")

    def history(self, start, end, integration_id=None, *, limit=1000, offset=0):
        with self._connect() as conn:
            return conn.execute('''SELECT a.day,a.integration_id,a.summary,a.computed_at,
                NOT EXISTS(SELECT 1 FROM cp_daily_aggregate_queue q WHERE q.day=a.day AND q.integration_id=a.integration_id) AS up_to_date,
                NOT EXISTS(SELECT 1 FROM cp_daily_aggregate_detail_gaps g WHERE g.day=a.day AND g.integration_id=a.integration_id) AS details_retained
                FROM cp_daily_scan_aggregates a
                WHERE day >= %s AND day < %s AND (%s::text IS NULL OR integration_id=%s)
                ORDER BY day,integration_id LIMIT %s OFFSET %s''',(start,end,integration_id,integration_id,limit,offset)).fetchall()

    def ready_days(self, start, end, integration_id=None):
        """Closed UTC days are usable only after backfill and all affected summaries finish."""
        today = datetime.now(timezone.utc).date()
        end_day = min(end.date(),today)
        with self._connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if conn.execute('SELECT EXISTS(SELECT 1 FROM cp_management_backfill WHERE NOT complete) AS pending').fetchone()['pending']:
                return {}
            dirty = {r['day'] for r in conn.execute('SELECT DISTINCT day FROM cp_daily_aggregate_queue WHERE day >= %s AND day < %s AND (%s::text IS NULL OR integration_id=%s)',(start.date(),end_day,integration_id,integration_id)).fetchall()}
            gaps = {r['day'] for r in conn.execute('SELECT DISTINCT day FROM cp_daily_aggregate_detail_gaps WHERE day >= %s AND day < %s AND (%s::text IS NULL OR integration_id=%s)',(start.date(),end_day,integration_id,integration_id)).fetchall()}
            rows = conn.execute('SELECT day,summary FROM cp_daily_scan_aggregates WHERE day >= %s AND day < %s AND (%s::text IS NULL OR integration_id=%s)',(start.date(),end_day,integration_id,integration_id)).fetchall()
        stored_days = {row['day'] for row in rows}
        result = {}
        day = start.date()
        while day < end_day:
            if (day not in dirty and day not in gaps) or (day in gaps and day in stored_days):
                result[day] = []
            day += timedelta(days=1)
        for row in rows:
            if row['day'] in result:
                result[row['day']].append(row['summary'])
        return result
