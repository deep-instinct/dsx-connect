CREATE TABLE IF NOT EXISTS cp_discovery_settings (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
    settings JSONB NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO cp_discovery_settings(singleton, settings) VALUES(TRUE,
    '{"periodic_enabled":true,"interval_seconds":300,"concurrency":2,"retry_initial_seconds":60,"retry_max_seconds":900,"max_pages_per_pass":10,"request_timeout_seconds":10}'::jsonb)
ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS cp_discovery_settings_audit (
    event_id BIGSERIAL PRIMARY KEY, changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revision BIGINT NOT NULL, previous_settings JSONB NOT NULL, settings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS cp_discovery_refresh_queue (
    integration_id TEXT PRIMARY KEY REFERENCES cp_integrations(integration_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL, reason TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ, outcome TEXT
);
CREATE TABLE IF NOT EXISTS cp_discovery_refresh_audit (
    request_id TEXT PRIMARY KEY, integration_id TEXT NOT NULL, reason TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), completed_at TIMESTAMPTZ, outcome TEXT
);
CREATE INDEX IF NOT EXISTS idx_discovery_refresh_pending ON cp_discovery_refresh_queue(requested_at) WHERE completed_at IS NULL;
ALTER TABLE cp_asset_inventory_status ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cp_asset_inventory_status ADD COLUMN IF NOT EXISTS active_request_id TEXT;
CREATE TABLE IF NOT EXISTS cp_discovery_workers (
    worker_id TEXT PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), active_connectors INTEGER NOT NULL DEFAULT 0
);
CREATE OR REPLACE FUNCTION cp_queue_discovery_refresh(p_integration TEXT, p_reason TEXT) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE token TEXT := md5(random()::text || clock_timestamp()::text);
BEGIN
    IF p_reason NOT IN ('manual', 'connector_online') THEN RAISE EXCEPTION 'Invalid discovery request reason'; END IF;
    -- Serialize requests for the same connector; a newer request cannot be acknowledged by older work.
    PERFORM pg_advisory_xact_lock(hashtextextended('discovery-request:' || p_integration, 0));
    UPDATE cp_discovery_refresh_audit SET completed_at = clock_timestamp(), outcome = 'superseded'
    WHERE request_id = (SELECT request_id FROM cp_discovery_refresh_queue WHERE integration_id = p_integration AND completed_at IS NULL);
    INSERT INTO cp_discovery_refresh_queue(integration_id, request_id, reason) VALUES(p_integration, token, p_reason)
    ON CONFLICT (integration_id) DO UPDATE SET request_id = EXCLUDED.request_id, reason = EXCLUDED.reason,
        requested_at = clock_timestamp(), completed_at = NULL, outcome = NULL;
    INSERT INTO cp_discovery_refresh_audit(request_id, integration_id, reason) VALUES(token, p_integration, p_reason);
    RETURN token;
END;
$$;
CREATE OR REPLACE FUNCTION cp_discover_connector_online() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' OR OLD.expires_at <= NEW.last_seen_at THEN
        IF EXISTS (SELECT 1 FROM cp_integrations WHERE integration_id = NEW.integration_id AND enabled AND capability_discover) THEN
            PERFORM cp_queue_discovery_refresh(NEW.integration_id, 'connector_online');
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS cp_discovery_online ON cp_connector_instances;
CREATE TRIGGER cp_discovery_online AFTER INSERT OR UPDATE ON cp_connector_instances
FOR EACH ROW EXECUTE FUNCTION cp_discover_connector_online();
