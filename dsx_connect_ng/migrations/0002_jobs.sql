CREATE TABLE IF NOT EXISTS cp_job_outbox (
    outbox_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES cp_jobs(job_id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    publish_state TEXT NOT NULL DEFAULT 'pending',
    publish_attempts INTEGER NOT NULL DEFAULT 0,
    last_error_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_cp_jobs_state_created_at
    ON cp_jobs (state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cp_jobs_integration_state_created_at
    ON cp_jobs (integration_id, state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cp_job_outbox_publish_state_created_at
    ON cp_job_outbox (publish_state, created_at);
