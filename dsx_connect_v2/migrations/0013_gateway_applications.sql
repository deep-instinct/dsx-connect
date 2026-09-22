CREATE TABLE IF NOT EXISTS cp_gateway_applications (
    application_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    identity_bindings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    tenant_id TEXT NULL,
    tenant_name TEXT NULL,
    customer_id TEXT NULL,
    customer_name TEXT NULL,
    business_unit TEXT NULL,
    submitted_by TEXT NULL,
    cost_center TEXT NULL,
    billing_code TEXT NULL,
    default_protected_entity_id INTEGER NULL,
    default_protected_entity_name TEXT NULL,
    grants_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cp_gateway_applications_enabled
    ON cp_gateway_applications (enabled);
