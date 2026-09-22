CREATE UNLOGGED TABLE IF NOT EXISTS cp_scan_runtime_leases (
    job_item_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cp_scan_runtime_leases_job_id
    ON cp_scan_runtime_leases (job_id);
