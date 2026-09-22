CREATE TABLE IF NOT EXISTS cp_job_items (
    job_item_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES cp_jobs(job_id) ON DELETE CASCADE,
    item_index INTEGER NOT NULL,
    object_identity TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cp_job_items_job_id_item_index
    ON cp_job_items (job_id, item_index);

CREATE INDEX IF NOT EXISTS idx_cp_job_items_job_id_state
    ON cp_job_items (job_id, state);
