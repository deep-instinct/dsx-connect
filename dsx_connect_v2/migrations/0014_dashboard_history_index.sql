-- Historical dashboard reads use the update window before inspecting stage times.
CREATE INDEX IF NOT EXISTS idx_cp_job_items_updated_at ON cp_job_items (updated_at);
