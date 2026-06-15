-- DSX-Connect Control Plane Schema (PostgreSQL)
-- Draft v1: additive schema for integrations, scopes, outcome policy, and domain jobs.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Integrations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_integrations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    platform            TEXT NOT NULL,
    tenant_key          TEXT NOT NULL, -- e.g., aws-account-id, m365-tenant-id
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    config_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, tenant_key, name)
);

-- ---------------------------------------------------------------------------
-- Protected scopes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_scopes (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id              UUID NOT NULL REFERENCES cp_integrations(id) ON DELETE CASCADE,
    external_scope_key          TEXT NOT NULL,
    display_name                TEXT NOT NULL DEFAULT '',
    container                   TEXT NOT NULL,
    scope_type                  TEXT NOT NULL CHECK (scope_type IN ('path', 'identity')),
    resource_selector           TEXT NOT NULL, -- path prefix or stable identity
    filter_expression           TEXT NOT NULL DEFAULT '',
    mode                        TEXT NOT NULL DEFAULT 'monitor' CHECK (mode IN ('monitor', 'full_scan')),
    enabled                     BOOLEAN NOT NULL DEFAULT TRUE,
    post_scan_policy_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (integration_id, external_scope_key)
);

CREATE INDEX IF NOT EXISTS ix_cp_scopes_integration ON cp_scopes(integration_id);
CREATE INDEX IF NOT EXISTS ix_cp_scopes_container ON cp_scopes(integration_id, container);
CREATE INDEX IF NOT EXISTS ix_cp_scopes_resource_selector ON cp_scopes(integration_id, resource_selector);

-- ---------------------------------------------------------------------------
-- Coverage configuration (protect all, exclude specific containers)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_coverage_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id      UUID NOT NULL REFERENCES cp_integrations(id) ON DELETE CASCADE,
    container_kind      TEXT NOT NULL, -- bucket/site/mailbox/team/channel
    enabled             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (integration_id, container_kind)
);

CREATE TABLE IF NOT EXISTS cp_coverage_exclusions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coverage_rule_id    UUID NOT NULL REFERENCES cp_coverage_rules(id) ON DELETE CASCADE,
    container_name      TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (coverage_rule_id, container_name)
);

-- ---------------------------------------------------------------------------
-- Full scan jobs (scope-level ownership)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_full_scan_jobs (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id              UUID NOT NULL REFERENCES cp_integrations(id) ON DELETE CASCADE,
    scope_id                    UUID NOT NULL REFERENCES cp_scopes(id) ON DELETE CASCADE,
    external_full_scan_key      TEXT,
    status                      TEXT NOT NULL CHECK (status IN ('queued','running','completed','failed','canceled')),
    requested_by                TEXT NOT NULL DEFAULT 'manual',
    started_at                  TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    objects_discovered          BIGINT NOT NULL DEFAULT 0,
    objects_scanned             BIGINT NOT NULL DEFAULT 0,
    objects_skipped             BIGINT NOT NULL DEFAULT 0,
    malicious_count             BIGINT NOT NULL DEFAULT 0,
    failed_count                BIGINT NOT NULL DEFAULT 0,
    retry_count                 BIGINT NOT NULL DEFAULT 0,
    checkpoint_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (external_full_scan_key)
);

-- One active full scan per scope.
CREATE UNIQUE INDEX IF NOT EXISTS ux_cp_full_scan_jobs_one_active_per_scope
    ON cp_full_scan_jobs(scope_id)
    WHERE status IN ('queued', 'running');

-- ---------------------------------------------------------------------------
-- Domain job ledger (canonical job envelope)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_jobs (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_job_key            TEXT,
    job_type                    TEXT NOT NULL,
    state                       TEXT NOT NULL CHECK (state IN ('queued','running','completed','failed','skipped','canceled')),
    integration_id              UUID NOT NULL REFERENCES cp_integrations(id) ON DELETE CASCADE,
    scope_id                    UUID REFERENCES cp_scopes(id) ON DELETE SET NULL,
    full_scan_job_id            UUID REFERENCES cp_full_scan_jobs(id) ON DELETE SET NULL,
    object_identity             TEXT,
    parent_job_id               UUID REFERENCES cp_jobs(id) ON DELETE SET NULL,
    root_job_id                 UUID,
    correlation_id              TEXT,
    source_type                 TEXT, -- monitoring|full_scan|manual
    source_entity_id            TEXT,
    idempotency_key             TEXT NOT NULL,
    attempt                     INT NOT NULL DEFAULT 0,
    max_attempts                INT NOT NULL DEFAULT 5,
    outcome                     TEXT, -- clean|malicious|unable_to_scan|...
    outcome_reason              TEXT,
    payload_json                JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_json                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    scheduled_at                TIMESTAMPTZ,
    started_at                  TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    UNIQUE (external_job_key),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_cp_jobs_state ON cp_jobs(state);
CREATE INDEX IF NOT EXISTS ix_cp_jobs_type_state ON cp_jobs(job_type, state);
CREATE INDEX IF NOT EXISTS ix_cp_jobs_scope_created ON cp_jobs(scope_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_cp_jobs_full_scan ON cp_jobs(full_scan_job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_cp_jobs_root ON cp_jobs(root_job_id);

-- ---------------------------------------------------------------------------
-- Idempotency ledger (optional explicit table; cp_jobs unique key is primary)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_idempotency_keys (
    key                         TEXT PRIMARY KEY,
    job_id                      UUID REFERENCES cp_jobs(id) ON DELETE CASCADE,
    first_seen_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at                  TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- Outbound events/audit stream
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cp_outbox_events (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type                  TEXT NOT NULL,
    aggregate_type              TEXT NOT NULL, -- job|scope|integration|full_scan
    aggregate_id                TEXT NOT NULL,
    payload_json                JSONB NOT NULL,
    published                   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at                TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_cp_outbox_unpublished ON cp_outbox_events(published, created_at);

COMMIT;
