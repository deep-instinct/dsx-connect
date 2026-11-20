-- Summaries have no foreign key to jobs/items: eventual detail retention must not cascade into history.
CREATE TABLE IF NOT EXISTS cp_daily_scan_aggregates (
    day DATE NOT NULL, integration_id TEXT NOT NULL,
    summary JSONB NOT NULL, computed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(day, integration_id)
);
CREATE TABLE IF NOT EXISTS cp_daily_aggregate_queue (
    day DATE NOT NULL, integration_id TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1, requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(day, integration_id)
);
CREATE INDEX IF NOT EXISTS idx_daily_aggregate_due ON cp_daily_aggregate_queue(available_at, requested_at);
CREATE TABLE IF NOT EXISTS cp_management_backfill (
    source TEXT PRIMARY KEY, last_id TEXT NOT NULL DEFAULT '', complete BOOLEAN NOT NULL DEFAULT FALSE
);
INSERT INTO cp_management_backfill(source) VALUES('items'),('jobs') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS cp_management_settings (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
    settings JSONB NOT NULL DEFAULT '{"aggregates_enabled":true,"aggregate_interval_seconds":300,"aggregate_days_per_pass":1}',
    revision BIGINT NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO cp_management_settings(singleton) VALUES(TRUE) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS cp_management_settings_audit (
    event_id BIGSERIAL PRIMARY KEY, changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revision BIGINT NOT NULL, previous_settings JSONB NOT NULL, settings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS cp_management_workers (
    worker_id TEXT PRIMARY KEY, last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS cp_management_tasks (
    task TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'pending',
    last_attempt_at TIMESTAMPTZ, last_completed_at TIMESTAMPTZ, detail TEXT
);
INSERT INTO cp_management_tasks(task) VALUES('daily_aggregates') ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION cp_aggregate_day(raw TEXT) RETURNS DATE LANGUAGE plpgsql AS $$
BEGIN
    RETURN (raw::timestamptz AT TIME ZONE 'UTC')::date;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END;
$$;
CREATE OR REPLACE FUNCTION cp_queue_daily_aggregate(p_day DATE, p_integration TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE delay INTEGER;
BEGIN
    IF p_day IS NULL THEN RETURN; END IF;
    SELECT (settings->>'aggregate_interval_seconds')::integer INTO delay FROM cp_management_settings WHERE singleton;
    INSERT INTO cp_daily_aggregate_queue(day, integration_id, available_at)
    VALUES(p_day, COALESCE(p_integration,''), clock_timestamp() +
        CASE WHEN p_day < (clock_timestamp() AT TIME ZONE 'UTC')::date THEN INTERVAL '0 seconds'
             ELSE make_interval(secs => COALESCE(delay,300)) END)
    ON CONFLICT(day, integration_id) DO UPDATE SET revision = cp_daily_aggregate_queue.revision + 1;
END;
$$;
CREATE OR REPLACE FUNCTION cp_dirty_daily_aggregate() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE row_data JSONB; old_data JSONB; connector TEXT; days DATE[]; value DATE;
BEGIN
    row_data := to_jsonb(NEW);
    IF TG_OP = 'UPDATE' THEN old_data := to_jsonb(OLD); END IF;
    IF TG_TABLE_NAME = 'cp_job_items' THEN
        IF TG_OP = 'UPDATE' AND
            (row_data->'scan_stage_json',row_data->'policy_stage_json',row_data->'remediation_stage_json') IS NOT DISTINCT FROM
            (old_data->'scan_stage_json',old_data->'policy_stage_json',old_data->'remediation_stage_json') THEN RETURN NEW; END IF;
        SELECT integration_id INTO connector FROM cp_jobs WHERE job_id = NEW.job_id AND job_type <> 'protection.bulk';
        IF NOT FOUND THEN RETURN NEW; END IF;
        days := ARRAY[cp_aggregate_day(row_data->'scan_stage_json'->>'completed_at'), cp_aggregate_day(old_data->'scan_stage_json'->>'completed_at'),
            cp_aggregate_day(row_data->'policy_stage_json'->>'completed_at'), cp_aggregate_day(old_data->'policy_stage_json'->>'completed_at'),
            cp_aggregate_day(row_data->'remediation_stage_json'->>'completed_at'), cp_aggregate_day(old_data->'remediation_stage_json'->>'completed_at')];
    ELSE
        IF NEW.job_type = 'protection.bulk' THEN RETURN NEW; END IF;
        IF TG_OP = 'UPDATE' AND (NEW.state,NEW.completed_at,NEW.integration_id,NEW.created_at) IS NOT DISTINCT FROM
            (OLD.state,OLD.completed_at,OLD.integration_id,OLD.created_at) THEN RETURN NEW; END IF;
        connector := NEW.integration_id;
        days := ARRAY[cp_aggregate_day(row_data->>'completed_at'), cp_aggregate_day(old_data->>'completed_at')];
        IF TG_OP = 'UPDATE' AND OLD.integration_id IS DISTINCT FROM NEW.integration_id THEN
            FOREACH value IN ARRAY days LOOP PERFORM cp_queue_daily_aggregate(value, OLD.integration_id); END LOOP;
        END IF;
    END IF;
    FOR value IN SELECT DISTINCT d FROM unnest(days) d WHERE d IS NOT NULL LOOP
        PERFORM cp_queue_daily_aggregate(value, connector);
    END LOOP;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS cp_dirty_daily_aggregate ON cp_job_items;
CREATE TRIGGER cp_dirty_daily_aggregate AFTER INSERT OR UPDATE ON cp_job_items FOR EACH ROW EXECUTE FUNCTION cp_dirty_daily_aggregate();
DROP TRIGGER IF EXISTS cp_dirty_daily_aggregate ON cp_jobs;
CREATE TRIGGER cp_dirty_daily_aggregate AFTER INSERT OR UPDATE ON cp_jobs FOR EACH ROW EXECUTE FUNCTION cp_dirty_daily_aggregate();

-- Safeguard retained history against an accidental rebuild after source details disappear.
-- This is not a purge policy: no source rows are deleted by management tasks.
CREATE TABLE IF NOT EXISTS cp_daily_aggregate_detail_gaps (
    day DATE NOT NULL, integration_id TEXT NOT NULL, first_removed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(day,integration_id)
);
CREATE OR REPLACE FUNCTION cp_preserve_daily_on_delete() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE connector TEXT; dates DATE[]; value DATE;
BEGIN
    IF TG_TABLE_NAME = 'cp_job_items' THEN
        SELECT integration_id INTO connector FROM cp_jobs WHERE job_id=OLD.job_id AND job_type <> 'protection.bulk';
        IF NOT FOUND THEN RETURN OLD; END IF;
        dates := ARRAY[cp_aggregate_day(OLD.scan_stage_json->>'completed_at'),cp_aggregate_day(OLD.policy_stage_json->>'completed_at'),cp_aggregate_day(OLD.remediation_stage_json->>'completed_at')];
    ELSE
        IF OLD.job_type = 'protection.bulk' THEN RETURN OLD; END IF;
        connector := OLD.integration_id;
        SELECT array_agg(DISTINCT day) INTO dates FROM (
            SELECT cp_aggregate_day(stage->>'completed_at') AS day FROM cp_job_items item,
                LATERAL unnest(ARRAY[item.scan_stage_json,item.policy_stage_json,item.remediation_stage_json]) stage
            WHERE item.job_id=OLD.job_id
            UNION SELECT cp_aggregate_day(OLD.completed_at::text)
        ) days;
    END IF;
    FOREACH value IN ARRAY COALESCE(dates, ARRAY[]::date[]) LOOP
        IF value IS NOT NULL THEN
            INSERT INTO cp_daily_aggregate_detail_gaps(day,integration_id) VALUES(value,COALESCE(connector,'')) ON CONFLICT DO NOTHING;
        END IF;
    END LOOP;
    RETURN OLD;
END;
$$;
DROP TRIGGER IF EXISTS cp_preserve_daily ON cp_job_items;
CREATE TRIGGER cp_preserve_daily BEFORE DELETE ON cp_job_items FOR EACH ROW EXECUTE FUNCTION cp_preserve_daily_on_delete();
DROP TRIGGER IF EXISTS cp_preserve_daily ON cp_jobs;
CREATE TRIGGER cp_preserve_daily BEFORE DELETE ON cp_jobs FOR EACH ROW EXECUTE FUNCTION cp_preserve_daily_on_delete();

ALTER TABLE cp_job_items ADD COLUMN IF NOT EXISTS report_scan_completed_at TIMESTAMPTZ;
ALTER TABLE cp_job_items ADD COLUMN IF NOT EXISTS report_policy_completed_at TIMESTAMPTZ;
ALTER TABLE cp_job_items ADD COLUMN IF NOT EXISTS report_remediation_completed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_items_report_scan ON cp_job_items(report_scan_completed_at) WHERE report_scan_completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_report_policy ON cp_job_items(report_policy_completed_at) WHERE report_policy_completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_items_report_remediation ON cp_job_items(report_remediation_completed_at) WHERE report_remediation_completed_at IS NOT NULL;
CREATE OR REPLACE FUNCTION cp_aggregate_timestamp(raw TEXT) RETURNS TIMESTAMPTZ LANGUAGE plpgsql AS $$
BEGIN RETURN raw::timestamptz;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END;
$$;
CREATE OR REPLACE FUNCTION cp_update_reporting_times() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.report_scan_completed_at := cp_aggregate_timestamp(NEW.scan_stage_json->>'completed_at');
    NEW.report_policy_completed_at := cp_aggregate_timestamp(NEW.policy_stage_json->>'completed_at');
    NEW.report_remediation_completed_at := cp_aggregate_timestamp(NEW.remediation_stage_json->>'completed_at');
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS cp_reporting_times ON cp_job_items;
CREATE TRIGGER cp_reporting_times BEFORE INSERT OR UPDATE OF scan_stage_json,policy_stage_json,remediation_stage_json ON cp_job_items
FOR EACH ROW EXECUTE FUNCTION cp_update_reporting_times();
