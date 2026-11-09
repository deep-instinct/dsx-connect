CREATE TABLE IF NOT EXISTS cp_scan_schedules (
    scope_id TEXT PRIMARY KEY REFERENCES cp_scopes(scope_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL,
    frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly')),
    local_time TIME NOT NULL,
    timezone TEXT NOT NULL,
    weekday SMALLINT CHECK (weekday BETWEEN 0 AND 6),
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_outcome TEXT CHECK (last_outcome IN ('submitted', 'skipped', 'failed')),
    last_reason TEXT,
    last_job_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_cp_scan_schedules_due
    ON cp_scan_schedules(next_run_at) WHERE enabled;
