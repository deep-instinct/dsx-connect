CREATE INDEX IF NOT EXISTS idx_cp_job_items_job_id_completed_at_terminal
    ON cp_job_items (job_id, completed_at)
    WHERE state IN ('completed', 'failed', 'cancelled');

CREATE INDEX IF NOT EXISTS idx_cp_job_items_job_id_policy_pending
    ON cp_job_items (job_id)
    WHERE scan_stage_json->>'state' = 'completed'
      AND policy_stage_json->>'state' = 'pending';
