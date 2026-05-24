ALTER TABLE cp_job_items
    ADD COLUMN IF NOT EXISTS policy_stage_json JSONB NOT NULL DEFAULT '{"state":"pending","started_at":null,"completed_at":null,"result":null,"error":null}'::jsonb;
