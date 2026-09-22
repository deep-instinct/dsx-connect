ALTER TABLE cp_job_items
    ADD COLUMN IF NOT EXISTS dianna_stage_json JSONB NOT NULL DEFAULT '{"state":"pending"}'::jsonb;
