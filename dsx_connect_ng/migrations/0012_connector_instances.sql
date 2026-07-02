CREATE TABLE IF NOT EXISTS cp_connector_instances (
    connector_instance_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES cp_integrations(integration_id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    platform_key TEXT NOT NULL,
    connector_name TEXT NOT NULL,
    connector_version TEXT NULL,
    base_url TEXT NOT NULL,
    capabilities_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    health TEXT NOT NULL DEFAULT 'unknown' CHECK (health IN ('unknown', 'healthy', 'degraded', 'unhealthy')),
    labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    lease_seconds INTEGER NOT NULL DEFAULT 120 CHECK (lease_seconds >= 15 AND lease_seconds <= 86400),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '120 seconds',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_connector_instances_integration
    ON cp_connector_instances (integration_id);

CREATE INDEX IF NOT EXISTS idx_cp_connector_instances_platform_key
    ON cp_connector_instances (platform, platform_key);

CREATE INDEX IF NOT EXISTS idx_cp_connector_instances_expires_at
    ON cp_connector_instances (expires_at);
