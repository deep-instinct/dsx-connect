CREATE TABLE IF NOT EXISTS cp_integrations (
    integration_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    platform_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    capability_discover BOOLEAN NOT NULL DEFAULT TRUE,
    capability_monitor BOOLEAN NOT NULL DEFAULT TRUE,
    capability_enumerate BOOLEAN NOT NULL DEFAULT FALSE,
    capability_read BOOLEAN NOT NULL DEFAULT FALSE,
    capability_remediate BOOLEAN NOT NULL DEFAULT FALSE,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (platform, platform_key)
);

CREATE TABLE IF NOT EXISTS cp_scopes (
    scope_id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES cp_integrations(integration_id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('path', 'identity')),
    resource_selector TEXT NOT NULL,
    normalized_selector TEXT NOT NULL,
    display_name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('monitor', 'full_scan')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    filter_expression TEXT NULL,
    post_scan_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_scopes_integration_scope_type
    ON cp_scopes (integration_id, scope_type);

CREATE INDEX IF NOT EXISTS idx_cp_scopes_integration_normalized_selector
    ON cp_scopes (integration_id, normalized_selector);

CREATE TABLE IF NOT EXISTS cp_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    state TEXT NOT NULL,
    integration_id TEXT NULL REFERENCES cp_integrations(integration_id) ON DELETE SET NULL,
    scope_id TEXT NULL REFERENCES cp_scopes(scope_id) ON DELETE SET NULL,
    object_identity TEXT NULL,
    idempotency_key TEXT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_jobs_idempotency_key
    ON cp_jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
