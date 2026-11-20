-- Configuration-only audit: no credentials, policies, or connector secrets.
CREATE TABLE IF NOT EXISTS cp_protection_audit_epoch (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    started_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp()
);
INSERT INTO cp_protection_audit_epoch(singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS cp_protection_events (
    event_id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('integration', 'scope', 'schedule', 'asset')),
    entity_id TEXT NOT NULL,
    integration_id TEXT,
    operation TEXT NOT NULL CHECK (operation IN ('baseline', 'INSERT', 'UPDATE', 'DELETE')),
    state JSONB NOT NULL
);
ALTER TABLE cp_protection_events DROP CONSTRAINT IF EXISTS cp_protection_events_entity_type_check;
ALTER TABLE cp_protection_events ADD CONSTRAINT cp_protection_events_entity_type_check
    CHECK (entity_type IN ('integration', 'scope', 'schedule', 'asset'));
ALTER TABLE cp_protection_events ALTER COLUMN occurred_at SET DEFAULT clock_timestamp();
CREATE INDEX IF NOT EXISTS idx_protection_events_entity_time
    ON cp_protection_events(entity_type, entity_id, occurred_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_protection_events_integration_time
    ON cp_protection_events(integration_id, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS idx_protection_events_time ON cp_protection_events(occurred_at, event_id);

CREATE TABLE IF NOT EXISTS cp_protection_revision (
    integration_id TEXT PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0
);
INSERT INTO cp_protection_revision(integration_id, revision)
SELECT '*', count(*) FROM cp_protection_events ON CONFLICT DO NOTHING;
INSERT INTO cp_protection_revision(integration_id, revision)
SELECT integration_id, count(*) FROM cp_protection_events WHERE integration_id IS NOT NULL GROUP BY integration_id
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS cp_discovered_assets (
    asset_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL,
    selector TEXT NOT NULL,
    normalized_selector TEXT NOT NULL,
    display_name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('configuration', 'discovery')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS idx_discovered_assets_integration ON cp_discovered_assets(integration_id, active);
CREATE TABLE IF NOT EXISTS cp_asset_inventory_status (
    integration_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('refreshing', 'partial', 'complete', 'error', 'unsupported', 'disabled')),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_completed_at TIMESTAMPTZ,
    run_started_at TIMESTAMPTZ,
    next_cursor TEXT,
    detail TEXT
);

CREATE OR REPLACE FUNCTION cp_audit_protection_configuration() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    source JSONB;
    previous JSONB;
    fields TEXT[];
    kind TEXT;
    entity TEXT;
    integration TEXT;
    snapshot JSONB;
BEGIN
    IF TG_TABLE_NAME = 'cp_integrations' THEN
        kind := 'integration';
        fields := ARRAY['integration_id', 'display_name', 'enabled', 'capability_monitor', 'capability_enumerate', 'capability_read'];
    ELSIF TG_TABLE_NAME = 'cp_scopes' THEN
        kind := 'scope';
        fields := ARRAY['scope_id', 'integration_id', 'display_name', 'resource_selector', 'normalized_selector', 'scope_type', 'enabled', 'mode'];
    ELSIF TG_TABLE_NAME = 'cp_discovered_assets' THEN
        kind := 'asset';
        fields := ARRAY['asset_id', 'integration_id', 'selector', 'normalized_selector', 'display_name', 'asset_type', 'source', 'active'];
    ELSE
        kind := 'schedule';
        fields := ARRAY['scope_id', 'enabled', 'frequency', 'local_time', 'timezone', 'weekday'];
    END IF;
    source := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    SELECT jsonb_object_agg(key, value) INTO snapshot FROM jsonb_each(source) WHERE key = ANY(fields);
    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(key, value) INTO previous FROM jsonb_each(to_jsonb(OLD)) WHERE key = ANY(fields);
        IF snapshot IS NOT DISTINCT FROM previous THEN RETURN NEW; END IF;
    END IF;
    entity := CASE WHEN kind = 'integration' THEN source->>'integration_id' WHEN kind = 'asset' THEN source->>'asset_id' ELSE source->>'scope_id' END;
    integration := source->>'integration_id';
    IF kind = 'schedule' THEN
        SELECT integration_id INTO integration FROM cp_scopes WHERE scope_id = entity;
        IF integration IS NULL THEN
            SELECT integration_id INTO integration FROM cp_protection_events
            WHERE entity_type = 'scope' AND entity_id = entity ORDER BY event_id DESC LIMIT 1;
        END IF;
    END IF;
    IF kind = 'scope' AND TG_OP <> 'DELETE' THEN
        INSERT INTO cp_discovered_assets(asset_id, integration_id, selector, normalized_selector, display_name, asset_type, source)
        VALUES (md5(integration || chr(31) || btrim(btrim(source->>'resource_selector'), '/')),
                integration, source->>'resource_selector', btrim(btrim(source->>'resource_selector'), '/'),
                source->>'display_name', 'configured', 'configuration')
        ON CONFLICT (asset_id) DO NOTHING;
    END IF;
    INSERT INTO cp_protection_revision(integration_id, revision) VALUES ('*', 1)
        ON CONFLICT (integration_id) DO UPDATE SET revision = cp_protection_revision.revision + 1;
    IF integration IS NOT NULL THEN
        INSERT INTO cp_protection_revision(integration_id, revision) VALUES (integration, 1)
            ON CONFLICT (integration_id) DO UPDATE SET revision = cp_protection_revision.revision + 1;
    END IF;
    INSERT INTO cp_protection_events(entity_type, entity_id, integration_id, operation, state)
        VALUES (kind, entity, integration, TG_OP, snapshot);
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

-- Locks cover the baseline and trigger installation in the migration transaction.
LOCK TABLE cp_integrations, cp_scopes, cp_scan_schedules IN SHARE ROW EXCLUSIVE MODE;
INSERT INTO cp_protection_events(occurred_at, entity_type, entity_id, integration_id, operation, state)
SELECT transaction_timestamp(), 'integration', i.integration_id, i.integration_id, 'baseline',
       jsonb_build_object('integration_id', i.integration_id, 'display_name', i.display_name,
                         'enabled', i.enabled, 'capability_monitor', i.capability_monitor,
                         'capability_enumerate', i.capability_enumerate, 'capability_read', i.capability_read)
FROM cp_integrations i WHERE NOT EXISTS (SELECT 1 FROM cp_protection_events e WHERE e.entity_type = 'integration' AND e.entity_id = i.integration_id);
INSERT INTO cp_protection_events(occurred_at, entity_type, entity_id, integration_id, operation, state)
SELECT transaction_timestamp(), 'scope', s.scope_id, s.integration_id, 'baseline',
       jsonb_build_object('scope_id', s.scope_id, 'integration_id', s.integration_id,
                         'display_name', s.display_name, 'resource_selector', s.resource_selector, 'normalized_selector', s.normalized_selector, 'scope_type', s.scope_type,
                         'enabled', s.enabled, 'mode', s.mode)
FROM cp_scopes s WHERE NOT EXISTS (SELECT 1 FROM cp_protection_events e WHERE e.entity_type = 'scope' AND e.entity_id = s.scope_id);
INSERT INTO cp_protection_events(occurred_at, entity_type, entity_id, integration_id, operation, state)
SELECT transaction_timestamp(), 'schedule', s.scope_id, c.integration_id, 'baseline',
       jsonb_build_object('scope_id', s.scope_id, 'enabled', s.enabled, 'frequency', s.frequency,
                         'local_time', s.local_time, 'timezone', s.timezone, 'weekday', s.weekday)
FROM cp_scan_schedules s JOIN cp_scopes c USING(scope_id)
WHERE NOT EXISTS (SELECT 1 FROM cp_protection_events e WHERE e.entity_type = 'schedule' AND e.entity_id = s.scope_id);

INSERT INTO cp_discovered_assets(asset_id, integration_id, selector, normalized_selector, display_name, asset_type, source)
SELECT md5(integration_id || chr(31) || btrim(btrim(resource_selector), '/')), integration_id,
       resource_selector, btrim(btrim(resource_selector), '/'), display_name, 'configured', 'configuration'
FROM cp_scopes ON CONFLICT (asset_id) DO NOTHING;
INSERT INTO cp_protection_events(occurred_at, entity_type, entity_id, integration_id, operation, state)
SELECT transaction_timestamp(), 'asset', a.asset_id, a.integration_id, 'baseline',
       jsonb_build_object('asset_id', a.asset_id, 'integration_id', a.integration_id, 'selector', a.selector,
                         'normalized_selector', a.normalized_selector, 'display_name', a.display_name,
                         'asset_type', a.asset_type, 'source', a.source, 'active', a.active)
FROM cp_discovered_assets a WHERE NOT EXISTS
    (SELECT 1 FROM cp_protection_events e WHERE e.entity_type = 'asset' AND e.entity_id = a.asset_id);
DROP TRIGGER IF EXISTS cp_protection_audit ON cp_discovered_assets;
CREATE TRIGGER cp_protection_audit AFTER INSERT OR UPDATE OR DELETE ON cp_discovered_assets
FOR EACH ROW EXECUTE FUNCTION cp_audit_protection_configuration();

CREATE OR REPLACE FUNCTION cp_inventory_status_revision() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO cp_protection_revision(integration_id, revision) VALUES ('*', 1)
        ON CONFLICT (integration_id) DO UPDATE SET revision = cp_protection_revision.revision + 1;
    INSERT INTO cp_protection_revision(integration_id, revision) VALUES (NEW.integration_id, 1)
        ON CONFLICT (integration_id) DO UPDATE SET revision = cp_protection_revision.revision + 1;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS cp_inventory_revision ON cp_asset_inventory_status;
CREATE TRIGGER cp_inventory_revision AFTER INSERT OR UPDATE ON cp_asset_inventory_status
FOR EACH ROW EXECUTE FUNCTION cp_inventory_status_revision();

DROP TRIGGER IF EXISTS cp_protection_audit ON cp_integrations;
CREATE TRIGGER cp_protection_audit AFTER INSERT OR UPDATE OR DELETE ON cp_integrations
FOR EACH ROW EXECUTE FUNCTION cp_audit_protection_configuration();
DROP TRIGGER IF EXISTS cp_protection_audit ON cp_scopes;
CREATE TRIGGER cp_protection_audit AFTER INSERT OR UPDATE OR DELETE ON cp_scopes
FOR EACH ROW EXECUTE FUNCTION cp_audit_protection_configuration();
DROP TRIGGER IF EXISTS cp_protection_audit ON cp_scan_schedules;
CREATE TRIGGER cp_protection_audit AFTER INSERT OR UPDATE OR DELETE ON cp_scan_schedules
FOR EACH ROW EXECUTE FUNCTION cp_audit_protection_configuration();
