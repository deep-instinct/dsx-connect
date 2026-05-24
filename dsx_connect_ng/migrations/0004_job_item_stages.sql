ALTER TABLE cp_job_items
    ADD COLUMN IF NOT EXISTS scan_stage_json JSONB NOT NULL DEFAULT '{"state":"pending"}'::jsonb,
    ADD COLUMN IF NOT EXISTS remediation_stage_json JSONB NOT NULL DEFAULT '{"state":"pending"}'::jsonb,
    ADD COLUMN IF NOT EXISTS delivery_stage_json JSONB NOT NULL DEFAULT '{"state":"pending"}'::jsonb;
