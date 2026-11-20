import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import psycopg

from dsx_connect_v2.jobs.postgres_repo import apply_schema, PostgresJobRepository
from dsx_connect_v2.jobs.daily_aggregates import DailyAggregateStore
from dsx_connect_v2.jobs.dashboard import dashboard_history

URL = os.getenv('DSX_CONNECT_V2_TEST_POSTGRES_URL')
pytestmark = pytest.mark.skipif(not URL, reason='requires PostgreSQL test database')


@pytest.fixture
def daily():
    name = 'daily_' + uuid.uuid4().hex
    with psycopg.connect(URL,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    url = make_conninfo(URL,options=f'-csearch_path={name}')
    apply_schema(url)
    store = DailyAggregateStore(url)
    day = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=2)
    with store._connect() as conn:
        conn.execute("INSERT INTO cp_integrations(integration_id,platform,platform_key,display_name) VALUES('i','s3','key','Test')")
        conn.execute("INSERT INTO cp_jobs(job_id,job_type,state,integration_id,created_at,completed_at) VALUES('j','scan.full','completed','i',%s,%s)",(day,day+timedelta(minutes=5)))
    try:
        yield store,url,day
    finally:
        with psycopg.connect(URL,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


def add_item(store, day, key='a', verdict='malicious', seconds=1):
    stage = dict(state='completed',completed_at=(day+timedelta(seconds=seconds)).isoformat(),
                 metadata=dict(workerElapsedMs=seconds*1000),result=dict(verdict=verdict,scan_duration_in_microseconds=seconds*1000000,file_info={'file_type':'PDF'}))
    policy = dict(state='completed',completed_at=(day+timedelta(seconds=seconds+1)).isoformat(),result={'decision_trace':{'policy_reason':'malware'}})
    remediation = dict(state='completed',completed_at=(day+timedelta(seconds=seconds+2)).isoformat(),result={'action':'quarantine','outcome':'succeeded'})
    with store._connect() as conn:
        conn.execute("INSERT INTO cp_job_items(job_item_id,job_id,item_index,object_identity,state,created_at,completed_at,scan_stage_json,policy_stage_json,remediation_stage_json) VALUES(%s,'j',%s,'file','completed',%s,%s,%s,%s,%s)",
                     (key,ord(key),day,day+timedelta(seconds=seconds+3),Jsonb(stage),Jsonb(policy),Jsonb(remediation)))
    return stage


def drain(store):
    while store.process_one():
        pass
    with store._connect() as conn:
        conn.execute('UPDATE cp_management_backfill SET complete=TRUE')


def test_summaries_are_exact_idempotent_and_survive_detail_deletion(daily):
    store,url,day = daily
    add_item(store,day)
    add_item(store,day,'b','clean',3)
    drain(store)
    summary = store.history(day.date(),(day+timedelta(days=1)).date())[0]['summary']
    assert summary['total'] == 2 and summary['benign'] == summary['malicious'] == 1
    assert summary['quarantined']['malicious'] == 1 and summary['quarantined']['other'] == 1
    assert summary['file_types'] == {'PDF':2}
    assert summary['jobs'] == {'completed':1}
    assert summary['timings']['scan_worker']['median_seconds'] == 2
    assert summary['timings']['scan_worker']['p99_seconds'] == summary['timings']['scan_worker']['max_seconds'] == 3
    assert not store.process_one()
    now = datetime.now(timezone.utc)
    before = dashboard_history(PostgresJobRepository(url),7,now)
    assert before['total_scans'] == 2 and before['daily_aggregate_days'] > 0
    with store._connect() as conn:
        conn.execute("DELETE FROM cp_jobs WHERE job_id='j'")
    after = dashboard_history(PostgresJobRepository(url),7,now)
    assert after['total_scans'] == before['total_scans']
    assert after['quarantined'] == before['quarantined']
    assert after['file_types'] == before['file_types']
    assert after['jobs'] == before['jobs']


def test_late_updates_invalidate_old_day_and_refresh_without_double_counting(daily):
    store,url,day = daily
    stage = add_item(store,day)
    drain(store)
    stage['result']['verdict'] = 'clean'
    with store._connect() as conn:
        conn.execute("UPDATE cp_job_items SET scan_stage_json=%s WHERE job_item_id='a'",(Jsonb(stage),))
    assert day.date() not in store.ready_days(day,datetime.now(timezone.utc))
    drain(store)
    summary = store.history(day.date(),(day+timedelta(days=1)).date())[0]['summary']
    assert summary['total'] == summary['benign'] == 1 and summary['malicious'] == 0
    assert day.date() in store.ready_days(day,datetime.now(timezone.utc))
    assert store.ready_days(day,datetime.now(timezone.utc),'other')[day.date()] == []


def test_bounded_backfill_resumes_and_schema_reapplication_does_not_reset_it(daily):
    store,url,day = daily
    add_item(store,day)
    add_item(store,day,'b')
    with store._connect() as conn:
        conn.execute('DELETE FROM cp_daily_aggregate_queue')
    store.backfill_page(limit=1)
    with store._connect() as conn:
        p=conn.execute("SELECT * FROM cp_management_backfill WHERE source='items'").fetchone()
        assert p['last_id']=='a' and not p['complete']
    apply_schema(url)
    store.backfill_page(limit=1)
    with store._connect() as conn:
        assert conn.execute("SELECT last_id FROM cp_management_backfill WHERE source='items'").fetchone()['last_id']=='b'
    for _ in range(5):
        store.backfill_page(limit=1)
    assert all(row['complete'] for row in store.status()['backfill'])
    drain(store)
    assert store.history(day.date(),(day+timedelta(days=1)).date())[0]['summary']['total']==2


def test_atomic_queue_keeps_rollback_and_concurrent_lock_safe(daily):
    store,url,day = daily
    with pytest.raises(RuntimeError):
        with store._connect() as conn:
            conn.execute("SELECT cp_queue_daily_aggregate(%s,'rolled-back')",(day.date(),))
            raise RuntimeError()
    with store._connect() as conn:
        assert not conn.execute("SELECT 1 FROM cp_daily_aggregate_queue WHERE integration_id='rolled-back'").fetchone()
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('management:daily-aggregates',0))")
        assert store.process_one() is False
    assert store.process_one() is True


def test_timing_validation_and_day_boundary_do_not_count_invalid_or_next_day_samples(daily):
    store,url,day = daily
    stage=add_item(store,day)
    stage['metadata']={'workerElapsedMs':'bad','requestElapsedMs':500}
    stage['result']['scan_duration_in_microseconds']=-1
    stage['metadata']['scannerEngineElapsedMs']=250
    with store._connect() as conn:
        conn.execute("UPDATE cp_job_items SET scan_stage_json=%s WHERE job_item_id='a'",(Jsonb(stage),))
    add_item(store,day+timedelta(days=1),'b','clean',0)
    drain(store)
    summary=store.history(day.date(),(day+timedelta(days=1)).date())[0]['summary']
    assert summary['total']==1
    assert summary['timings']['scan_worker']['median_seconds']==.5
    assert summary['timings']['dsxa']['median_seconds']==.25


def test_source_removal_never_allows_partial_rebuild_to_overwrite_retained_summary(daily):
    store,url,day=daily
    add_item(store,day)
    add_item(store,day,'b')
    drain(store)
    with store._connect() as conn:
        conn.execute("DELETE FROM cp_job_items WHERE job_item_id='a'")
        conn.execute("SELECT cp_queue_daily_aggregate(%s,'i')",(day.date(),))
    assert store.process_one() is False
    archived=store.history(day.date(),(day+timedelta(days=1)).date())[0]
    assert archived['summary']['total']==2 and not archived['details_retained']
    assert store.ready_days(day,datetime.now(timezone.utc))[day.date()][0]['total']==2


def test_management_policy_is_audited_and_rejects_stale_edits(daily):
    from dsx_connect_v2.jobs.daily_aggregates import ManagementSettings
    store,_,_=daily
    first=store.settings()
    new=store.save_settings(ManagementSettings(aggregate_interval_seconds=60),first['revision'])
    assert new['revision']==first['revision']+1
    assert store.save_settings(ManagementSettings(aggregate_interval_seconds=60),new['revision'])['revision']==new['revision']
    with pytest.raises(ValueError,match='changed'):
        store.save_settings(ManagementSettings(),first['revision'])
    with store._connect() as conn:
        assert conn.execute('SELECT count(*) FROM cp_management_settings_audit').fetchone()['count']==1


def test_completion_date_correction_refreshes_both_days(daily):
    store,_,day=daily
    stage=add_item(store,day)
    drain(store)
    stage['completed_at']=(day+timedelta(days=1,seconds=1)).isoformat()
    with store._connect() as conn:
        conn.execute("UPDATE cp_job_items SET scan_stage_json=%s WHERE job_item_id='a'",(Jsonb(stage),))
        queued={r['day'] for r in conn.execute('SELECT day FROM cp_daily_aggregate_queue').fetchall()}
    assert {day.date(),(day+timedelta(days=1)).date()} <= queued
    drain(store)
    rows=store.history(day.date(),(day+timedelta(days=2)).date())
    assert [r['summary']['total'] for r in rows]==[0,1]


def test_refresh_requested_during_summary_write_is_not_acknowledged_by_old_revision(daily):
    store,_,day=daily
    add_item(store,day)
    with store._connect() as conn:
        conn.execute("""CREATE FUNCTION request_again() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN PERFORM cp_queue_daily_aggregate(NEW.day,NEW.integration_id); RETURN NEW; END; $$;
            CREATE TRIGGER request_again AFTER INSERT ON cp_daily_scan_aggregates FOR EACH ROW EXECUTE FUNCTION request_again();""")
    assert store.process_one()
    with store._connect() as conn:
        assert conn.execute('SELECT count(*) FROM cp_daily_aggregate_queue').fetchone()['count']==1
        conn.execute('DROP TRIGGER request_again ON cp_daily_scan_aggregates')
    assert store.process_one()
    with store._connect() as conn:
        assert conn.execute('SELECT count(*) FROM cp_daily_aggregate_queue').fetchone()['count']==0
